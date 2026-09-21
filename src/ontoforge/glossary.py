"""The glossary of a domain: business terms and KPI metrics, each tied to a table, its columns and
an ontology class, with a steward and an approval status."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from ontoforge.db import Database
from ontoforge.registry import Registry
from ontoforge.registry.models import NotFound

KINDS = ("term", "metric")
STATUSES = ("draft", "pending", "approved", "certified")


@dataclass(frozen=True)
class Term:
    id: UUID
    domain_id: UUID
    kind: str
    name: str
    definition: str
    status: str
    schema_name: str | None
    table_name: str | None
    columns: list[str]
    class_name: str | None
    formula: str | None
    unit: str | None
    frequency: str | None
    owner: str | None
    created_by: str | None
    created_at: datetime
    updated_by: str | None
    updated_at: datetime

    def to_dict(self) -> dict:
        d = asdict(self)
        d["id"], d["domain_id"] = str(self.id), str(self.domain_id)
        d["created_at"], d["updated_at"] = self.created_at.isoformat(), self.updated_at.isoformat()
        return d


class GlossaryService:
    def __init__(self, registry: Registry, db: Database) -> None:
        self.registry, self.db = registry, db

    def list(self, domain_id: UUID, *, kind: str | None = None, table: str | None = None, q: str | None = None) -> list[Term]:
        clauses, params = ["domain_id = %s"], [domain_id]
        if kind:
            clauses.append("kind = %s"); params.append(kind)
        if table:
            clauses.append("lower(table_name) = lower(%s)"); params.append(table)
        if q and q.strip():
            clauses.append("(name ILIKE %s OR definition ILIKE %s OR coalesce(formula, '') ILIKE %s OR coalesce(class_name, '') ILIKE %s OR columns::text ILIKE %s)")
            params += [f"%{q.strip()}%"] * 5
        with self.db.rows() as cur:
            rows = cur.execute(f"SELECT * FROM glossary_terms WHERE {' AND '.join(clauses)} ORDER BY created_at, name", params).fetchall()
        return [_term(r) for r in rows]

    def get(self, term_id: UUID) -> Term:
        with self.db.rows() as cur:
            row = cur.execute("SELECT * FROM glossary_terms WHERE id = %s", (term_id,)).fetchone()
        if not row:
            raise NotFound(f"Glossary entry {term_id}")
        return _term(row)

    def add(self, domain_id: UUID, *, actor: str, kind: str, name: str, definition: str = "", table: str | None = None, columns: list[str] | None = None,
            status: str = "draft", owner: str | None = None, class_name: str | None = None, formula: str | None = None, unit: str | None = None,
            frequency: str | None = None) -> Term:
        f = _validate(kind=kind, name=name, status=status, table=table, columns=columns or [])
        try:
            with self.db.rows() as cur:
                row = cur.execute(
                    "INSERT INTO glossary_terms (domain_id, kind, name, definition, status, schema_name, table_name, columns, class_name, formula, unit, frequency, owner, created_by, updated_by) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
                    (domain_id, f["kind"], f["name"], definition or "", f["status"], f["schema"], f["table"], Jsonb(f["columns"]), class_name, formula, unit, frequency, owner, actor, actor)).fetchone()
        except psycopg.errors.UniqueViolation:
            raise ValueError(f"A {kind} named {name!r} already exists in this glossary") from None
        return _term(row)

    def update(self, term_id: UUID, *, actor: str, **changes) -> Term:
        t = self.get(term_id)
        merged = {"kind": t.kind, "name": t.name, "status": t.status, "table": t.table_name, "columns": t.columns}
        merged.update({k: v for k, v in changes.items() if k in merged})
        if "table_name" in changes:
            merged["table"] = changes["table_name"]
        f = _validate(**merged)
        get = lambda k, cur: changes[k] if k in changes else cur
        try:
            with self.db.rows() as cur:
                row = cur.execute(
                    "UPDATE glossary_terms SET kind = %s, name = %s, definition = %s, status = %s, schema_name = %s, table_name = %s, columns = %s, class_name = %s, "
                    "formula = %s, unit = %s, frequency = %s, owner = %s, updated_by = %s, updated_at = now() WHERE id = %s RETURNING *",
                    (f["kind"], f["name"], get("definition", t.definition) or "", f["status"], f["schema"], f["table"], Jsonb(f["columns"]), get("class_name", t.class_name),
                     get("formula", t.formula), get("unit", t.unit), get("frequency", t.frequency), get("owner", t.owner), actor, term_id)).fetchone()
        except psycopg.errors.UniqueViolation:
            raise ValueError(f"A {f['kind']} named {f['name']!r} already exists in this glossary") from None
        return _term(row)

    def delete(self, term_id: UUID, *, actor: str) -> None:
        self.get(term_id)
        with self.db.rows() as cur:
            cur.execute("DELETE FROM glossary_terms WHERE id = %s", (term_id,))


def _validate(*, kind: str, name: str, status: str, table: str | None, columns: list[str]) -> dict:
    if kind not in KINDS:
        raise ValueError(f"A glossary entry is a term or a metric, not {kind!r}")
    if not name or not name.strip():
        raise ValueError("A glossary entry needs a name")
    if status not in STATUSES:
        raise ValueError(f"Unknown status {status!r}; choose from {', '.join(STATUSES)}")
    parts = (table or "").split(".")
    schema = parts[-2] if table and len(parts) >= 2 else None
    return {"kind": kind, "name": name.strip(), "status": status, "table": table or None, "schema": schema, "columns": [str(c) for c in columns if str(c).strip()]}


def _term(row: dict) -> Term:
    return Term(row["id"], row["domain_id"], row["kind"], row["name"], row["definition"], row["status"], row["schema_name"], row["table_name"],
                list(row["columns"] or []), row["class_name"], row["formula"], row["unit"], row["frequency"], row["owner"], row["created_by"],
                row["created_at"], row["updated_by"], row["updated_at"])
