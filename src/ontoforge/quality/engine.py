"""Validate constraints with SQL over the triples table: scales with the warehouse, not with RAM."""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from ontoforge.compiler import RDF_TYPE
from ontoforge.dialects import PostgresDialect
from ontoforge.ontology import Ontology
from ontoforge.registry import Registry
from ontoforge.store import TripleStore

from .derive import constraints_from_ontology
from .model import XSD_STRING, Constraint, ConstraintSet

_D = PostgresDialect()
_NUMERIC = r"'^-?[0-9]+(\.[0-9]+)?$'"


@dataclass
class ConstraintResult:
    name: str
    kind: str
    severity: str
    targets: int
    violations: int
    samples: list[dict]
    message: str


@dataclass
class QualityReport:
    results: list[ConstraintResult] = field(default_factory=list)

    @property
    def conforms(self) -> bool:
        return not any(r.violations for r in self.results if r.severity == "violation")

    @property
    def summary(self) -> dict[str, int]:
        out = {"violation": 0, "warning": 0, "info": 0}
        for r in self.results:
            out[r.severity] += r.violations
        return out


def compile_constraint(c: Constraint, version_id: UUID | str, ontology: Ontology | None = None) -> tuple[str, str]:
    """(targets_sql, violations_sql). Violations project (focus, value)."""
    vid = _D.string_literal(str(version_id))
    classes = [c.target_class, *(ontology.descendants(c.target_class) if ontology else ())]
    cls_list = ", ".join(_D.string_literal(x) for x in classes)
    rdf_type = _D.string_literal(RDF_TYPE)
    focus = (f"(SELECT DISTINCT subject FROM triples WHERE domain_version_id = {vid} AND predicate = {rdf_type} "
             f"AND object IN ({cls_list})) f")
    vals = (f"(SELECT subject, object, object_type, datatype FROM triples WHERE domain_version_id = {vid} "
            f"AND predicate = {_D.string_literal(c.property)}) v")
    targets = f"SELECT count(*) FROM {focus}"
    join = f"FROM {focus} JOIN {vals} ON v.subject = f.subject"
    num = f"(CASE WHEN v.object_type = 'literal' AND v.object ~ {_NUMERIC} THEN CAST(v.object AS numeric) END)"
    k, val = c.kind, c.value
    if k in ("min_count", "max_count"):
        op = "<" if k == "min_count" else ">"
        sql = (f"SELECT f.subject AS focus, CAST(count(v.object) AS text) AS value FROM {focus} LEFT JOIN {vals} "
               f"ON v.subject = f.subject GROUP BY f.subject HAVING count(v.object) {op} {int(val)}")
    elif k == "datatype":
        sql = (f"SELECT f.subject AS focus, v.object AS value {join} WHERE v.object_type <> 'literal' "
               f"OR coalesce(v.datatype, {_D.string_literal(XSD_STRING)}) <> {_D.string_literal(str(val))}")
    elif k == "class":
        expected = [str(val), *(ontology.descendants(str(val)) if ontology else ())]
        sql = (f"SELECT f.subject AS focus, v.object AS value {join} WHERE v.object_type = 'literal' OR NOT EXISTS ("
               f"SELECT 1 FROM triples t WHERE t.domain_version_id = {vid} AND t.subject = v.object AND t.predicate = {rdf_type} "
               f"AND t.object IN ({', '.join(_D.string_literal(x) for x in expected)}))")
    elif k == "pattern":
        sql = f"SELECT f.subject AS focus, v.object AS value {join} WHERE NOT (v.object ~ {_D.string_literal(str(val))})"
    elif k == "in":
        sql = f"SELECT f.subject AS focus, v.object AS value {join} WHERE v.object NOT IN ({', '.join(_D.string_literal(str(x)) for x in val)})"
    elif k in ("min_inclusive", "max_inclusive", "min_exclusive", "max_exclusive"):
        op = {"min_inclusive": ">=", "max_inclusive": "<=", "min_exclusive": ">", "max_exclusive": "<"}[k]
        sql = f"SELECT f.subject AS focus, v.object AS value {join} WHERE {num} IS NULL OR NOT ({num} {op} {val})"
    elif k == "unique":
        sql = (f"SELECT f.subject AS focus, v.object AS value {join} WHERE v.object IN (SELECT v2.object FROM {focus.replace(') f', ') f2')} "
               f"JOIN {vals.replace(') v', ') v2')} ON v2.subject = f2.subject GROUP BY v2.object HAVING count(DISTINCT v2.subject) > 1)")
    elif k == "node_kind":
        sql = f"SELECT f.subject AS focus, v.object AS value {join} WHERE v.object_type <> {_D.string_literal(str(val))}"
    else:  # pragma: no cover - guarded by Constraint validation
        raise ValueError(k)
    return targets, sql


class QualityEngine:
    SAMPLE_LIMIT = 20

    def __init__(self, registry: Registry, store: TripleStore) -> None:
        self.registry, self.store = registry, store

    def constraints_for(self, version_id: UUID, include_ontology: bool = True) -> tuple[ConstraintSet, Ontology | None]:
        version = self.registry.get_version(version_id)
        ontology = Ontology.from_turtle(version.ontology_ttl) if version.ontology_ttl else None
        authored = ConstraintSet.from_dict(version.quality).constraints
        derived = constraints_from_ontology(ontology).constraints if (include_ontology and ontology) else ()
        return ConstraintSet([*derived, *authored]), ontology

    def run(self, version_id: UUID, include_ontology: bool = True) -> QualityReport:
        cs, ontology = self.constraints_for(version_id, include_ontology)
        report = QualityReport()
        with self.store.db.transaction() as cur:
            for c in cs.constraints:
                targets_sql, viol_sql = compile_constraint(c, version_id, ontology)
                targets = cur.execute(targets_sql).fetchone()[0]
                count = cur.execute(f"SELECT count(*) FROM ({viol_sql}) q").fetchone()[0]
                message = c.message or c.default_message()
                samples = [{"focus": f, "value": v, "message": message}
                           for f, v in cur.execute(f"{viol_sql} ORDER BY 1 LIMIT {self.SAMPLE_LIMIT}").fetchall()]
                report.results.append(ConstraintResult(c.name, c.kind, c.severity, targets, count, samples, message))
        return report

    def sql(self, version_id: UUID, include_ontology: bool = True) -> str:
        cs, ontology = self.constraints_for(version_id, include_ontology)
        return "\n\n".join(f"-- {c.name} ({c.kind}, {c.severity})\n{compile_constraint(c, version_id, ontology)[1]}" for c in cs.constraints)
