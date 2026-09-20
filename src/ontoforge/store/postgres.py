"""Triple store over the shared ``triples`` table (one row per triple, keyed by domain version)."""
from __future__ import annotations

from typing import Iterable, Iterator
from uuid import UUID

from ontoforge.compiler import RDF_TYPE
from ontoforge.db import Database
from ontoforge.ontology import Ontology

from .models import Attribute, Edge, Entity, EntityDetail, Relation, Subgraph, TriplePage

_TRIPLE_SORT_COLUMNS = frozenset({"subject", "predicate", "object", "inferred"})

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
                               "AND subject NOT LIKE '\\_:%%' GROUP BY 1 ORDER BY 2 DESC, 1", (version_id, RDF_TYPE)).fetchall()

    def predicate_inventory(self, version_id: UUID) -> list[tuple[str, int]]:
        with self.db.transaction() as cur:
            return cur.execute("SELECT predicate, count(*) FROM triples WHERE domain_version_id = %s "
                               "GROUP BY 1 ORDER BY 2 DESC, 1", (version_id,)).fetchall()

    def search(self, version_id: UUID, text: str, type_iri: str | None = None, limit: int = 20,
               match: str = "contains", field: str = "any") -> list[Entity]:
        """Entities whose literal values (field=label), IRI (field=iri) or either (any) match ``text``.
        match: contains | exact | starts_with | ends_with. Ranked exact > prefix > contains, shortest first."""
        if match not in ("contains", "exact", "starts_with", "ends_with"):
            raise ValueError("match must be contains, exact, starts_with or ends_with")
        if field not in ("any", "label", "iri"):
            raise ValueError("field must be any, label or iri")
        esc = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = {"contains": f"%{esc}%", "exact": esc, "starts_with": f"{esc}%", "ends_with": f"%{esc}"}[match]
        q = text.lower()
        lit = "(t.object_type = 'literal' AND t.object ILIKE %s)"
        iri = "t.subject ILIKE %s"
        where = {"any": f"({lit} OR {iri})", "label": lit, "iri": iri}[field]
        params: list = [q, q + "%", version_id]
        params += [pattern, pattern] if field == "any" else [pattern]
        with self.db.transaction() as cur:
            rows = cur.execute(
                "SELECT t.subject, min(CASE WHEN lower(t.object) = %s THEN 0 WHEN lower(t.object) LIKE %s THEN 1 "
                "                          WHEN t.object_type = 'literal' THEN 2 ELSE 3 END) AS rank, min(length(t.object)) AS len "
                "FROM triples t WHERE t.domain_version_id = %s AND t.subject NOT LIKE '\\_:%%' "
                f"AND {where} "
                "AND (%s::text IS NULL OR EXISTS (SELECT 1 FROM triples ty WHERE ty.domain_version_id = t.domain_version_id "
                "     AND ty.subject = t.subject AND ty.predicate = %s AND ty.object = %s)) "
                "GROUP BY t.subject ORDER BY rank, len, t.subject LIMIT %s",
                (*params, type_iri, RDF_TYPE, type_iri, limit)).fetchall()
            iris = [r[0] for r in rows]
            order = {iri: i for i, iri in enumerate(iris)}
            return sorted(self._entities(cur, version_id, iris), key=lambda e: order[e.iri])

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

    def overview(self, version_id: UUID, limit: int = 300) -> Subgraph:
        """A first picture of the graph: a few relationships of every predicate, spread evenly."""
        with self.db.transaction() as cur:
            preds = [p for p, _ in cur.execute(
                "SELECT predicate, count(*) FROM triples WHERE domain_version_id = %s AND predicate <> %s AND object_type <> 'literal' "
                "AND subject NOT LIKE '\\_:%%' GROUP BY 1 ORDER BY 2 DESC", (version_id, RDF_TYPE)).fetchall()]
            if not preds:
                return Subgraph()
            per = max(1, limit // len(preds))
            edges: list[Edge] = []
            for p in preds:
                for s_, o in cur.execute("SELECT subject, object FROM triples WHERE domain_version_id = %s AND predicate = %s "
                                         "AND object_type <> 'literal' ORDER BY subject, object LIMIT %s", (version_id, p, per)):
                    edges.append(Edge(s_, p, o))
            edges = edges[:limit]
            iris = sorted({e.source for e in edges} | {e.target for e in edges})
            nodes = self._entities(cur, version_id, iris)
        return Subgraph(nodes=nodes, edges=edges)

    def triples(self, version_id: UUID, *, subject: str | None = None, predicate: str | None = None, text: str | None = None,
                inferred: bool | None = None, limit: int = 100, offset: int = 0,
                sort: str = "subject", direction: str = "asc") -> TriplePage:
        """Raw triple rows, filterable, sortable and paged, for the triples grid."""
        if sort not in _TRIPLE_SORT_COLUMNS:
            raise ValueError(f"Cannot sort triples by {sort!r}; choose from {sorted(_TRIPLE_SORT_COLUMNS)}")
        if direction not in ("asc", "desc"):
            raise ValueError(f"Sort direction must be 'asc' or 'desc', not {direction!r}")
        order = ", ".join(dict.fromkeys([f"{sort} {direction.upper()}", "subject", "predicate", "object"]))
        clauses, params = ["domain_version_id = %s"], [version_id]
        if subject:
            clauses.append("subject = %s"); params.append(subject)
        if predicate:
            clauses.append("predicate = %s"); params.append(predicate)
        if text:
            clauses.append("(object ILIKE %s OR subject ILIKE %s OR predicate ILIKE %s)"); params += [f"%{text}%"] * 3
        if inferred is not None:
            clauses.append("inferred = %s"); params.append(inferred)
        where = " AND ".join(clauses)
        with self.db.transaction() as cur:
            total = cur.execute(f"SELECT count(*) FROM triples WHERE {where}", params).fetchone()[0]
            rows = cur.execute(f"SELECT subject, predicate, object, object_type, datatype, lang, inferred FROM triples WHERE {where} "
                               f"ORDER BY {order} LIMIT %s OFFSET %s", (*params, limit, offset)).fetchall()
        cols = ("subject", "predicate", "object", "object_type", "datatype", "lang", "inferred")
        return TriplePage(total=total, rows=[dict(zip(cols, r)) for r in rows])

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
        ln = Ontology.local_name(p).lower()
        if ln in ("name", "label", "title", "fullname", "displayname") or ln.endswith(("name", "_label", "title")):
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
