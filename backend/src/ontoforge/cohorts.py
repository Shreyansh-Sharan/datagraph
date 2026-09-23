"""Cohorts: named groups of entities selected by explainable criteria.

A cohort is a class plus criteria over attributes, relationships, or attributes of related
entities. Evaluation runs one SQL query per criterion over the triples table and combines the
matches (all / any), keeping per-member evidence so every membership can be explained.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ontoforge.compiler import RDF_TYPE
from ontoforge.ontology import Ontology
from ontoforge.registry import NotFound, Registry
from ontoforge.store import TripleStore

COHORT_PREDICATE = "http://ontoforge.dev/analytics#inCohort"
KINDS = ("attribute", "relation", "related_attribute")
VALUE_OPS = ("eq", "neq", "gt", "gte", "lt", "lte", "matches", "contains", "exists", "missing")
RELATION_OPS = ("exists", "not_exists", "eq")
_NUMERIC = r"'^-?[0-9]+(\.[0-9]+)?$'"
_SQL_OP = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
_TEXT_OP = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "matches": "~", "contains": "LIKE"}


class CohortError(ValueError):
    pass


@dataclass(frozen=True)
class Criterion:
    kind: str
    property: str
    operator: str
    value: object = None
    via: str | None = None       # related_attribute: the attribute read on the related entity

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise CohortError(f"Unknown criterion kind {self.kind!r}; use one of {KINDS}")
        ops = RELATION_OPS if self.kind == "relation" else VALUE_OPS
        if self.operator not in ops:
            raise CohortError(f"Unknown operator {self.operator!r} for {self.kind}; use one of {ops}")
        if self.kind == "related_attribute" and not self.via:
            raise CohortError("related_attribute needs 'via': the attribute to read on the related entity")
        if self.operator not in ("exists", "missing", "not_exists") and self.value is None:
            raise CohortError(f"Operator {self.operator} needs a value")


@dataclass(frozen=True)
class Cohort:
    name: str
    class_iri: str
    criteria: tuple[Criterion, ...] = field(default_factory=tuple)
    description: str | None = None
    match: str = "all"

    def __post_init__(self) -> None:
        object.__setattr__(self, "criteria", tuple(self.criteria))
        if self.match not in ("all", "any"):
            raise CohortError("match must be 'all' or 'any'")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_\-]{0,119}", self.name):
            raise CohortError("Cohort name must be alphanumeric with '-' or '_'")
        if not self.criteria:
            raise CohortError("A cohort needs at least one criterion")

    def to_dict(self) -> dict:
        return {"name": self.name, "class_iri": self.class_iri, "description": self.description, "match": self.match,
                "criteria": [asdict(c) for c in self.criteria]}

    @classmethod
    def from_dict(cls, d: dict) -> Cohort:
        return cls(d["name"], d["class_iri"], tuple(Criterion(c["kind"], c["property"], c["operator"], c.get("value"), c.get("via"))
                                                    for c in d.get("criteria", [])), d.get("description"), d.get("match", "all"))


@dataclass
class Member:
    iri: str
    label: str
    explanation: list[str]


@dataclass
class CohortResult:
    name: str
    size: int
    total_candidates: int
    members: list[Member]


class CohortEngine:
    def __init__(self, registry: Registry, store: TripleStore) -> None:
        self.registry, self.store = registry, store

    # -- evaluation ----------------------------------------------------------

    def evaluate(self, version_id: UUID, cohort: Cohort, limit: int = 1000) -> CohortResult:
        version = self.registry.get_version(version_id)
        onto = Ontology.from_turtle(version.ontology_ttl) if version.ontology_ttl else None
        ln = onto.local_name if onto else Ontology.local_name
        classes = [cohort.class_iri, *(onto.descendants(cohort.class_iri) if onto else ())]
        with self.store.db.transaction() as cur:
            candidates = [r[0] for r in cur.execute(
                "SELECT DISTINCT subject FROM triples WHERE domain_version_id = %s AND predicate = %s AND object = ANY(%s) ORDER BY 1",
                (version_id, RDF_TYPE, classes))]
            evidence: dict[str, list[str]] = {c: [] for c in candidates}
            hit_sets: list[set[str]] = []
            for crit in cohort.criteria:
                hits = self._criterion(cur, version_id, crit, candidates, ln)
                hit_sets.append(set(hits))
                for subject, why in hits.items():
                    evidence[subject].append(why)
            if cohort.match == "all":
                selected = set(candidates).intersection(*hit_sets) if hit_sets else set()
            else:
                selected = set().union(*hit_sets)
            chosen = sorted(selected)[:limit]
            labels = {e.iri: e.label for e in self.store._entities(cur, version_id, chosen)}
        members = [Member(s, labels.get(s, ln(s)), evidence[s]) for s in chosen]
        return CohortResult(cohort.name, len(selected), len(candidates), members)

    def _criterion(self, cur, version_id: UUID, crit: Criterion, candidates: list[str], ln) -> dict[str, str]:
        """subject -> explanation for every candidate the criterion selects."""
        vals = ("SELECT subject, object, object_type FROM triples WHERE domain_version_id = %s AND predicate = %s AND subject = ANY(%s)")
        if crit.kind == "attribute":
            rows = cur.execute(vals, (version_id, crit.property, candidates)).fetchall()
            return self._value_match(rows, crit, candidates, f"{ln(crit.property)}")
        if crit.kind == "relation":
            rows = cur.execute(vals, (version_id, crit.property, candidates)).fetchall()
            have = {}
            for s, o, ot in rows:
                if ot != "literal" and (crit.operator != "eq" or o == crit.value):
                    have.setdefault(s, f"{ln(crit.property)} -> {ln(o)}" + (" exists" if crit.operator == "exists" else ""))
            if crit.operator == "not_exists":
                return {c: f"no {ln(crit.property)}" for c in candidates if c not in have}
            return have
        # related_attribute: attribute `via` of the entities reached through `property`
        rows = cur.execute(vals, (version_id, crit.property, candidates)).fetchall()
        targets = {(s, o) for s, o, ot in rows if ot != "literal"}
        target_iris = sorted({o for _, o in targets})
        attr_rows = cur.execute(vals, (version_id, crit.via, target_iris)).fetchall() if target_iris else []
        by_target = self._value_match(attr_rows, crit, target_iris, f"{ln(crit.property)} -> {ln(crit.via)}")
        out = {}
        for s, o in sorted(targets):
            if o in by_target:
                out.setdefault(s, by_target[o])
        return out

    @staticmethod
    def _value_match(rows, crit: Criterion, subjects: list[str], label: str) -> dict[str, str]:
        values: dict[str, list[str]] = {}
        for s, o, ot in rows:
            if ot == "literal":
                values.setdefault(s, []).append(o)
        if crit.operator == "missing":
            return {s: f"{label} missing" for s in subjects if s not in values}
        if crit.operator == "exists":
            return {s: f"{label} = {v[0]}" for s, v in values.items()}
        out = {}
        for s, vs in values.items():
            for v in vs:
                if _compare(v, crit.operator, crit.value):
                    out[s] = f"{label} = {v} ({_describe(crit)})"
                    break
        return out

    # -- storage & materialisation -------------------------------------------

    def save(self, version_id: UUID, cohort: Cohort, *, actor: str) -> Cohort:
        self.registry.get_version(version_id)
        with self.store.db.transaction() as cur:
            cur.execute("INSERT INTO cohorts (domain_version_id, name, definition, created_by) VALUES (%s, %s, %s, %s) "
                        "ON CONFLICT (domain_version_id, name) DO UPDATE SET definition = EXCLUDED.definition, updated_at = now()",
                        (version_id, cohort.name, Jsonb(cohort.to_dict()), actor))
        return cohort

    def list(self, version_id: UUID) -> list[Cohort]:
        with self.store.db.connection() as conn:
            rows = conn.cursor(row_factory=dict_row).execute(
                "SELECT definition FROM cohorts WHERE domain_version_id = %s ORDER BY name", (version_id,)).fetchall()
        return [Cohort.from_dict(r["definition"]) for r in rows]

    def get(self, version_id: UUID, name: str) -> Cohort:
        with self.store.db.connection() as conn:
            row = conn.cursor(row_factory=dict_row).execute(
                "SELECT definition FROM cohorts WHERE domain_version_id = %s AND name = %s", (version_id, name)).fetchone()
        if row is None:
            raise NotFound(f"Cohort {name!r}")
        return Cohort.from_dict(row["definition"])

    def delete(self, version_id: UUID, name: str, *, actor: str) -> None:
        self.get(version_id, name)
        with self.store.db.transaction() as cur:
            cur.execute("DELETE FROM cohorts WHERE domain_version_id = %s AND name = %s", (version_id, name))
            cur.execute("DELETE FROM triples WHERE domain_version_id = %s AND predicate = %s AND object = %s",
                        (version_id, COHORT_PREDICATE, self._target(version_id, name)))

    def materialise(self, version_id: UUID, name: str) -> CohortResult:
        cohort = self.get(version_id, name)
        result = self.evaluate(version_id, cohort, limit=10**9)
        target = self._target(version_id, name)
        with self.store.db.transaction() as cur:
            cur.execute("DELETE FROM triples WHERE domain_version_id = %s AND predicate = %s AND object = %s",
                        (version_id, COHORT_PREDICATE, target))
        self.store.add_inferred(version_id, ((m.iri, COHORT_PREDICATE, target, "iri", None, None) for m in result.members))
        return result

    def _target(self, version_id: UUID, name: str) -> str:
        version = self.registry.get_version(version_id)
        return f"{self.registry.get_domain_by_id(version.domain_id).base_iri}cohort/{name}"


def _compare(value: str, op: str, expected) -> bool:
    if op == "matches":
        return re.search(str(expected), value) is not None
    if op == "contains":
        return str(expected).lower() in value.lower()
    if isinstance(expected, (int, float)):
        try:
            v = float(value)
        except ValueError:
            return False
        return {"eq": v == expected, "neq": v != expected, "gt": v > expected, "gte": v >= expected,
                "lt": v < expected, "lte": v <= expected}[op]
    e = str(expected)
    return {"eq": value == e, "neq": value != e, "gt": value > e, "gte": value >= e, "lt": value < e, "lte": value <= e}[op]


def _describe(crit: Criterion) -> str:
    return {"eq": "=", "neq": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "matches": "~", "contains": "contains"}[crit.operator] + f" {crit.value}"
