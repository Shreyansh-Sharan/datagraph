"""Triple store over the shared ``triples`` table (one row per triple, keyed by domain version)."""
from __future__ import annotations

from typing import Iterable, Iterator
from uuid import UUID

from ontoforge.compiler import RDF_TYPE
from ontoforge.db import Database
from ontoforge.ontology import Ontology

from .models import Attribute, Edge, Entity, EntityDetail, Relation, Subgraph

RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
COLUMNS = ("subject", "predicate", "object", "object_type", "datatype", "lang")
Row = tuple  # (subject, predicate, object, object_type, datatype, lang)


class TripleStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- loading -------------------------------------------------------------

    def replace_from_sql(self, version_id: UUID, select_sql: str) -> int:
        """Full rebuild when the source tables live in this database: one server-side statement."""
        with self.db.transaction() as cur:
            cur.execute("DELETE FROM triples WHERE domain_version_id = %s", (version_id,))
            cur.execute(f"INSERT INTO triples (domain_version_id, {', '.join(COLUMNS)}) "
                        f"SELECT %s, {', '.join(COLUMNS)} FROM (\n{select_sql}\n) AS src", (version_id,))
            return cur.rowcount

    def replace(self, version_id: UUID, rows: Iterable[Row]) -> int:
        """Full rebuild from a stream of rows (source lives elsewhere); atomic."""
        with self.db.transaction() as cur:
            cur.execute("DELETE FROM triples WHERE domain_version_id = %s", (version_id,))
            return self._copy(cur, version_id, rows, inferred=False)

    def add_inferred(self, version_id: UUID, rows: Iterable[Row]) -> int:
        with self.db.transaction() as cur:
            return self._copy(cur, version_id, rows, inferred=True)

    def clear_inferred(self, version_id: UUID) -> int:
        with self.db.transaction() as cur:
            cur.execute("DELETE FROM triples WHERE domain_version_id = %s AND inferred", (version_id,))
            return cur.rowcount

    def clear(self, version_id: UUID) -> int:
        with self.db.transaction() as cur:
            cur.execute("DELETE FROM triples WHERE domain_version_id = %s", (version_id,))
            return cur.rowcount

    @staticmethod
    def _copy(cur, version_id: UUID, rows: Iterable[Row], inferred: bool) -> int:
        n = 0
        with cur.copy(f"COPY triples (domain_version_id, {', '.join(COLUMNS)}, inferred) FROM STDIN") as copy:
            for row in rows:
                copy.write_row((version_id, *row[:6], inferred))
                n += 1
        return n

    # -- reading -------------------------------------------------------------

    def count(self, version_id: UUID, inferred: bool | None = None) -> int:
        with self.db.transaction() as cur:
            return cur.execute("SELECT count(*) FROM triples WHERE domain_version_id = %s AND (%s::boolean IS NULL OR inferred = %s)",
                               (version_id, inferred, inferred)).fetchone()[0]

    def iter_triples(self, version_id: UUID, inferred: bool | None = False, batch: int = 10_000) -> Iterator[Row]:
        with self.db.connection() as conn:
            with conn.cursor(name=f"triples_{version_id.hex[:8]}") as cur:
                cur.itersize = batch
                cur.execute(f"SELECT {', '.join(COLUMNS)} FROM triples WHERE domain_version_id = %s "
                            "AND (%s::boolean IS NULL OR inferred = %s)", (version_id, inferred, inferred))
                yield from cur

    def type_inventory(self, version_id: UUID) -> list[tuple[str, int]]:
        with self.db.transaction() as cur:
            return cur.execute("SELECT object, count(*) FROM triples WHERE domain_version_id = %s AND predicate = %s "
                               "GROUP BY 1 ORDER BY 2 DESC, 1", (version_id, RDF_TYPE)).fetchall()

    def predicate_inventory(self, version_id: UUID) -> list[tuple[str, int]]:
        with self.db.transaction() as cur:
            return cur.execute("SELECT predicate, count(*) FROM triples WHERE domain_version_id = %s "
                               "GROUP BY 1 ORDER BY 2 DESC, 1", (version_id,)).fetchall()

    def search(self, version_id: UUID, text: str, type_iri: str | None = None, limit: int = 20) -> list[Entity]:
        pattern = f"%{text}%"
        with self.db.transaction() as cur:
            iris = [r[0] for r in cur.execute(
                "SELECT DISTINCT t.subject FROM triples t WHERE t.domain_version_id = %s "
                "AND ((t.object_type = 'literal' AND t.object ILIKE %s) OR t.subject ILIKE %s) "
                "AND (%s::text IS NULL OR EXISTS (SELECT 1 FROM triples ty WHERE ty.domain_version_id = t.domain_version_id "
                "     AND ty.subject = t.subject AND ty.predicate = %s AND ty.object = %s)) "
                "ORDER BY 1 LIMIT %s", (version_id, pattern, pattern, type_iri, RDF_TYPE, type_iri, limit))]
            return self._entities(cur, version_id, iris)

    def describe(self, version_id: UUID, iri: str) -> EntityDetail | None:
        with self.db.transaction() as cur:
            out = cur.execute("SELECT predicate, object, object_type, datatype, lang, inferred FROM triples "
                              "WHERE domain_version_id = %s AND subject = %s ORDER BY predicate, object", (version_id, iri)).fetchall()
            inc = cur.execute("SELECT predicate, subject, inferred FROM triples WHERE domain_version_id = %s "
                              "AND object_key = md5(%s) AND object = %s AND object_type <> 'literal' ORDER BY predicate, subject",
                              (version_id, iri, iri)).fetchall()
            if not out and not inc:
                return None
            types = tuple(o for p, o, *_ in out if p == RDF_TYPE)
            attrs = tuple(Attribute(p, o, dt, lg, inf) for p, o, ot, dt, lg, inf in out if ot == "literal")
            outgoing = tuple(Relation(p, target=o, inferred=inf) for p, o, ot, dt, lg, inf in out if ot != "literal" and p != RDF_TYPE)
            incoming = tuple(Relation(p, source=s, inferred=inf) for p, s, inf in inc)
            return EntityDetail(iri, _label(iri, attrs), types, attrs, outgoing, incoming)

    def neighbourhood(self, version_id: UUID, iri: str, depth: int = 1, limit: int = 500) -> Subgraph:
        seen, frontier, edges = {iri}, [iri], []
        with self.db.transaction() as cur:
            for _ in range(max(depth, 0)):
                if not frontier or len(seen) >= limit:
                    break
                rows = cur.execute(
                    "SELECT subject, predicate, object FROM triples WHERE domain_version_id = %s AND predicate <> %s "
                    "AND object_type <> 'literal' AND (subject = ANY(%s) OR (object_key = ANY(%s) AND object = ANY(%s))) "
                    "LIMIT %s", (version_id, RDF_TYPE, frontier, [_md5(x) for x in frontier], frontier, limit)).fetchall()
                nxt = []
                for s, p, o in rows:
                    edges.append(Edge(s, p, o))
                    for n in (s, o):
                        if n not in seen and len(seen) < limit:
                            seen.add(n)
                            nxt.append(n)
                frontier = nxt
            nodes = self._entities(cur, version_id, sorted(seen))
        unique_edges = list(dict.fromkeys(edges))
        return Subgraph(nodes=nodes, edges=unique_edges)

    # -- helpers -------------------------------------------------------------

    def _entities(self, cur, version_id: UUID, iris: list[str]) -> list[Entity]:
        if not iris:
            return []
        rows = cur.execute("SELECT subject, predicate, object, object_type FROM triples WHERE domain_version_id = %s "
                           "AND subject = ANY(%s) AND (predicate = %s OR object_type = 'literal')",
                           (version_id, iris, RDF_TYPE)).fetchall()
        types: dict[str, list[str]] = {i: [] for i in iris}
        attrs: dict[str, list[Attribute]] = {i: [] for i in iris}
        for s, p, o, ot in rows:
            (types[s].append(o) if p == RDF_TYPE else attrs[s].append(Attribute(p, o)))
        return [Entity(i, _label(i, attrs[i]), tuple(sorted(types[i]))) for i in iris]


def _label(iri: str, attrs) -> str:
    by_pred = {a.predicate: a.value for a in attrs}
    if RDFS_LABEL in by_pred:
        return by_pred[RDFS_LABEL]
    for p, v in by_pred.items():
        if Ontology.local_name(p).lower() in ("name", "label", "title", "fullname", "displayname"):
            return v
    return fallback_label(iri)


def fallback_label(iri: str) -> str:
    """``.../Employee/42`` -> ``Employee/42``; ``...#Thing`` -> ``Thing``."""
    if "#" in iri:
        return iri.rsplit("#", 1)[1] or iri
    parts = [p for p in iri.rstrip("/").split("/") if p]
    return "/".join(parts[-2:]) if len(parts) >= 2 and not parts[-2].startswith(("http:", "https:")) else (parts[-1] if parts else iri)


def _md5(text: str) -> str:
    import hashlib
    return hashlib.md5(text.encode()).hexdigest()
