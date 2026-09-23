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
# Distinct predicates of a version by walking the (domain_version_id, predicate, ...) index one step at a time.
_DISTINCT_PREDICATES = """
WITH RECURSIVE p AS (
    (SELECT predicate FROM triples WHERE domain_version_id = %s ORDER BY predicate LIMIT 1)
    UNION ALL
    SELECT (SELECT predicate FROM triples WHERE domain_version_id = %s AND predicate > p.predicate ORDER BY predicate LIMIT 1)
    FROM p WHERE p.predicate IS NOT NULL
)
SELECT predicate FROM p WHERE predicate IS NOT NULL"""


class TripleStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- loading -------------------------------------------------------------

    def replace_from_sql(self, version_id: UUID, select_sql: str, tables: list[str] | None = None, with_source: bool = False) -> int:
        """Rebuild when the source tables live in this database: one server-side statement. With ``tables``
        only the triples of those source tables are replaced; ``with_source`` means the SELECT carries a
        seventh column, source_table."""
        cols = list(COLUMNS) + (["source_table"] if with_source else [])
        with self.db.transaction() as cur:
            self._clear(cur, version_id, tables)
            cur.execute(f"INSERT INTO triples (domain_version_id, {', '.join(cols)}) "
                        f"SELECT %s, {', '.join(cols)} FROM (\n{select_sql}\n) AS src", (version_id,))
            return cur.rowcount

    def replace(self, version_id: UUID, rows: Iterable[Row]) -> int:
        """Full rebuild from a stream of rows (source lives elsewhere); atomic."""
        with self.db.transaction() as cur:
            cur.execute("DELETE FROM triples WHERE domain_version_id = %s", (version_id,))
            return self._copy(cur, version_id, rows, inferred=False)

    def analyze(self) -> None:
        """Refresh the planner's statistics on the triples table: after a load a version's rows are
        unknown to the planner, and it picks nested loops over full scans for every join."""
        with self.db.transaction() as cur:
            cur.execute("ANALYZE triples")

    def replace_tables(self, version_id: UUID, tables: list[str] | None, rows: Iterable[Row]) -> int:
        """Replace the triples of the given source tables (every table when None) from a stream of rows
        that carry their source table as a seventh value; atomic."""
        with self.db.transaction() as cur:
            self._clear(cur, version_id, tables)
            return self._copy(cur, version_id, rows, inferred=False, with_source=True)

    @staticmethod
    def _clear(cur, version_id: UUID, tables: list[str] | None) -> None:
        if tables is None:
            cur.execute("DELETE FROM triples WHERE domain_version_id = %s", (version_id,))
        else:
            cur.execute("DELETE FROM triples WHERE domain_version_id = %s AND NOT inferred AND source_table = ANY(%s)", (version_id, tables))

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
    def _copy(cur, version_id: UUID, rows: Iterable[Row], inferred: bool, with_source: bool = False) -> int:
        n = 0
        cols = f"domain_version_id, {', '.join(COLUMNS)}, inferred" + (", source_table" if with_source else "")
        with cur.copy(f"COPY triples ({cols}) FROM STDIN") as copy:
            for row in rows:
                copy.write_row((version_id, *row[:6], inferred, *((row[6],) if with_source else ())))
                n += 1
        return n

    # -- reading -------------------------------------------------------------

    def count(self, version_id: UUID, inferred: bool | None = None) -> int:
        with self.db.transaction() as cur:
            return cur.execute("SELECT count(*) FROM triples WHERE domain_version_id = %s AND (%s::boolean IS NULL OR inferred = %s)",
                               (version_id, inferred, inferred)).fetchone()[0]

    def counts(self, version_id: UUID) -> tuple[int, int]:
        """(all triples, inferred triples) in one pass over the version."""
        with self.db.transaction() as cur:
            total, inf = cur.execute("SELECT count(*), count(*) FILTER (WHERE inferred) FROM triples WHERE domain_version_id = %s",
                                     (version_id,)).fetchone()
            return int(total), int(inf)

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
        """A first picture of the graph: a few relationships of every predicate, spread evenly.

        Built for millions of triples: the predicates come from a loose index scan (one probe per
        distinct predicate, never a pass over the table), a predicate counts as a relationship when
        its first row has an IRI object, and each sample walks the (version, predicate) index."""
        with self.db.transaction() as cur:
            preds = [p for (p,) in cur.execute(_DISTINCT_PREDICATES, (version_id, version_id)).fetchall() if p != RDF_TYPE]
            rels = [p for p in preds if (cur.execute(
                "SELECT object_type FROM triples WHERE domain_version_id = %s AND predicate = %s LIMIT 1", (version_id, p)).fetchone() or ("literal",))[0] != "literal"]
            if not rels:
                return Subgraph()
            per = max(1, limit // len(rels))
            edges: list[Edge] = []
            for p in rels:
                for s_, o in cur.execute("SELECT subject, object FROM triples WHERE domain_version_id = %s AND predicate = %s "
                                         "AND object_type <> 'literal' AND subject NOT LIKE '\\_:%%' ORDER BY object_key LIMIT %s", (version_id, p, per)):
                    edges.append(Edge(s_, p, o))
            edges = edges[:limit]
            iris = sorted({e.source for e in edges} | {e.target for e in edges})
            nodes = self._entities(cur, version_id, iris)
        return Subgraph(nodes=nodes, edges=edges)

    def aggregate(self, version_id: UUID, class_iri: str, *, measure: str | None = None, group_by: "str | list[str] | None" = None,
                  group_kind: str = "value", filters: list[dict] | None = None, limit: int = 50) -> list[dict]:
        """Count the instances of a class, and sum/average a numeric datatype property, grouped by a
        property (its value, or the year / month of a date) reached directly or through a path of
        steps, keeping only instances that reach a value through a filter path. A step is a
        predicate IRI, or "^" + IRI to walk the relationship backwards."""
        jparams: list = []                      # bound in the JOINs, which come first in the statement
        wparams: list = [version_id, RDF_TYPE, class_iri]
        where = ["i.domain_version_id = %s AND i.predicate = %s AND i.object_key = md5(%s) AND i.subject NOT LIKE '\\_:%%'"]   # object_key: the (predicate, object) index
        joins: list[str] = []
        n = 0
        for f in filters or []:
            steps = f.get("path") or ([f["predicate"]] if f.get("predicate") else [])
            if not steps:
                continue
            n, end = self._walk(steps, "i.subject", joins, jparams, version_id, n)
            where.append(f"{end} = %s")
            wparams.append(str(f["value"]))
        gsteps = [group_by] if isinstance(group_by, str) else list(group_by or [])
        gexpr = "NULL"
        if gsteps:
            n, gend = self._walk(gsteps, "i.subject", joins, jparams, version_id, n, outer=True)
            gexpr = f"substr({gend}, 1, 4)" if group_kind == "year" else f"substr({gend}, 1, 7)" if group_kind == "month" else gend
        mexpr = "CAST(NULL AS double precision)"
        if measure:
            joins.append("LEFT JOIN triples m ON m.domain_version_id = %s AND m.subject = i.subject AND m.predicate = %s")
            jparams += [version_id, measure]
            mexpr = "NULLIF(regexp_replace(m.object, '[^0-9.eE-]', '', 'g'), '')::double precision"
        sql = (f"SELECT {gexpr} AS grp, count(DISTINCT i.subject) AS n, sum(x.v), avg(x.v), min(x.v), max(x.v) FROM triples i {' '.join(joins)} "
               f"CROSS JOIN LATERAL (SELECT {mexpr} AS v) x WHERE {' AND '.join(where)} GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {int(limit)}")
        with self.db.transaction() as cur:
            cur.execute("SET LOCAL statement_timeout = '90s'")   # a bad plan fails with a message instead of holding the caller for ever
            rows = cur.execute(sql, jparams + wparams).fetchall()
            iris = [r[0] for r in rows if isinstance(r[0], str) and r[0].startswith(("http://", "https://", "urn:"))]
            labels = {e.iri: e.label for e in self._entities(cur, version_id, iris)} if iris else {}
        out = []
        for grp, cnt, sm, av, mn, mx in rows:
            out.append({"group": grp, "label": labels.get(grp, grp), "count": int(cnt), "sum": _num(sm), "avg": _num(av), "min": _num(mn), "max": _num(mx)})
        return out

    def _walk(self, steps: list[str], start: str, joins: list[str], params: list, version_id: UUID, n: int, outer: bool = False) -> tuple[int, str]:
        """JOIN one triples alias per step from ``start``; returns the alias count and the end expression."""
        prev, kind = start, "LEFT JOIN" if outer else "JOIN"
        for step in steps:
            n += 1
            a = f"s{n}"
            if step.startswith("^"):
                joins.append(f"{kind} triples {a} ON {a}.domain_version_id = %s AND {a}.predicate = %s AND {a}.object = {prev}")
                params += [version_id, step[1:]]
                prev = f"{a}.subject"
            else:
                joins.append(f"{kind} triples {a} ON {a}.domain_version_id = %s AND {a}.predicate = %s AND {a}.subject = {prev}")
                params += [version_id, step]
                prev = f"{a}.object"
        return n, prev

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

    def entities(self, version_id: UUID, iris: list[str]) -> list[Entity]:
        """Label and types of each IRI (for naming the neighbours of an entity in one round trip)."""
        with self.db.transaction() as cur:
            return self._entities(cur, version_id, sorted(set(iris)))

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



def _num(v) -> float | None:
    return None if v is None else round(float(v), 4)
