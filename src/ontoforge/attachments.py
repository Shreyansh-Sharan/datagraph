"""Datasets, class actions and virtual attributes: SQL attached to ontology classes and run against
the source warehouse on demand, with the entity's key columns bound as parameters.

Nothing here is materialised into the graph; results are always live.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from uuid import UUID

from ontoforge.build.source import SourceEngine
from ontoforge.mapping import MappingSpec
from ontoforge.ontology import Ontology
from ontoforge.registry import Registry

_PLACEHOLDER = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")
KINDS = ("scalar", "table")


class AttachmentError(ValueError):
    pass


def _check_sql(sql: str, what: str) -> str:
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        raise AttachmentError(f"{what}: SQL is empty")
    if ";" in sql:
        raise AttachmentError(f"{what}: SQL must be a single statement without ';'")
    if not sql.lower().startswith(("select", "with")):
        raise AttachmentError(f"{what}: only SELECT statements are allowed")
    return sql


@dataclass(frozen=True)
class Dataset:
    class_iri: str
    table: str
    key_columns: tuple[str, ...]           # columns in `table` matching the class key, in order
    description: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "key_columns", tuple(self.key_columns))
        if not self.key_columns:
            raise AttachmentError(f"Dataset {self.table}: key_columns is required")


@dataclass(frozen=True)
class Action:
    class_iri: str
    name: str
    sql: str
    description: str | None = None
    kind: str = "table"

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise AttachmentError(f"Action {self.name}: kind must be one of {KINDS}")
        object.__setattr__(self, "sql", _check_sql(self.sql, f"Action {self.name}"))


@dataclass(frozen=True)
class VirtualAttribute:
    class_iri: str
    name: str
    sql: str
    description: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "sql", _check_sql(self.sql, f"Virtual attribute {self.name}"))


@dataclass(frozen=True)
class Attachments:
    datasets: tuple[Dataset, ...] = field(default_factory=tuple)
    actions: tuple[Action, ...] = field(default_factory=tuple)
    virtual_attributes: tuple[VirtualAttribute, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "datasets", tuple(self.datasets))
        object.__setattr__(self, "actions", tuple(self.actions))
        object.__setattr__(self, "virtual_attributes", tuple(self.virtual_attributes))
        for items, what in ((self.actions, "Action"), (self.virtual_attributes, "Virtual attribute")):
            keys = [(x.class_iri, x.name) for x in items]
            if len(set(keys)) != len(keys):
                raise AttachmentError(f"{what} names must be unique per class")

    def classes(self) -> set[str]:
        return {x.class_iri for x in (*self.datasets, *self.actions, *self.virtual_attributes)}

    def to_dict(self) -> dict:
        return {"datasets": [asdict(d) for d in self.datasets], "actions": [asdict(a) for a in self.actions],
                "virtual_attributes": [asdict(v) for v in self.virtual_attributes]}

    @classmethod
    def from_dict(cls, d: dict | None) -> Attachments:
        d = d or {}
        return cls(tuple(Dataset(x["class_iri"], x["table"], tuple(x["key_columns"]), x.get("description")) for x in d.get("datasets", [])),
                   tuple(Action(x["class_iri"], x["name"], x["sql"], x.get("description"), x.get("kind", "table")) for x in d.get("actions", [])),
                   tuple(VirtualAttribute(x["class_iri"], x["name"], x["sql"], x.get("description")) for x in d.get("virtual_attributes", [])))


class AttachmentService:
    def __init__(self, registry: Registry, source: SourceEngine) -> None:
        self.registry, self.source = registry, source

    # -- lookup ------------------------------------------------------------------

    def _load(self, version_id: UUID) -> tuple[Attachments, MappingSpec | None]:
        v = self.registry.get_version(version_id)
        return Attachments.from_dict(v.attachments), (MappingSpec.from_dict(v.mapping) if v.mapping else None)

    def _resolve(self, spec: MappingSpec | None, iri: str) -> tuple[str, dict[str, str]]:
        """(class IRI, key column values) for an entity IRI, via the class's subject template."""
        if spec is not None:
            for c in spec.classes:
                values = spec.key_values_from_iri(c.class_iri, iri)
                if values is not None:
                    return c.class_iri, values
        raise AttachmentError(f"Entity {iri} does not match any mapped class")

    def for_class(self, version_id: UUID, class_iri: str) -> dict:
        att, _ = self._load(version_id)
        return {"datasets": [asdict(d) for d in att.datasets if d.class_iri == class_iri],
                "actions": sorted(({"name": a.name, "description": a.description, "kind": a.kind} for a in att.actions if a.class_iri == class_iri),
                                  key=lambda a: a["name"]),
                "virtual_attributes": sorted(v.name for v in att.virtual_attributes if v.class_iri == class_iri)}

    # -- execution ---------------------------------------------------------------

    def compute_virtual(self, version_id: UUID, iri: str) -> dict[str, str | None]:
        att, spec = self._load(version_id)
        cls, keys = self._resolve(spec, iri)
        out = {}
        for va in att.virtual_attributes:
            if va.class_iri == cls:
                _, rows = self._run(va.sql, keys, limit=1)
                out[va.name] = _text(rows[0][0]) if rows else None
        return out

    def invoke(self, version_id: UUID, iri: str, name: str) -> dict:
        att, spec = self._load(version_id)
        cls, keys = self._resolve(spec, iri)
        action = next((a for a in att.actions if a.name == name), None)
        if action is None:
            raise AttachmentError(f"There is no action named {name!r}")
        if action.class_iri != cls:
            raise AttachmentError(f"Action {name!r} is declared on {Ontology.local_name(action.class_iri)}, "
                                  f"not on {Ontology.local_name(cls)}")
        columns, rows = self._run(action.sql, keys, limit=1 if action.kind == "scalar" else 500)
        if action.kind == "scalar":
            return {"kind": "scalar", "value": _text(rows[0][0]) if rows else None}
        return {"kind": "table", "columns": columns, "rows": [dict(zip(columns, (_text(v) for v in r))) for r in rows]}

    def dataset_rows(self, version_id: UUID, iri: str, limit: int = 50) -> list[dict]:
        att, spec = self._load(version_id)
        cls, keys = self._resolve(spec, iri)
        cm = next(c for c in spec.classes if c.class_iri == cls)
        out = []
        for ds in att.datasets:
            if ds.class_iri != cls:
                continue
            if len(ds.key_columns) != len(cm.key_columns):
                raise AttachmentError(f"Dataset {ds.table}: key_columns must match the class key ({len(cm.key_columns)} column(s))")
            q = self.source.dialect.quote_identifier
            where = " AND ".join(f"{q(col)} = :{col}" for col in ds.key_columns)
            params = {col: keys[k] for col, k in zip(ds.key_columns, cm.key_columns)}
            order = ", ".join(q(c) for c in self.source.catalog.column_types(ds.table)) or "1"   # deterministic rows
            columns, rows = self._run(f"SELECT * FROM {self.source.dialect.quote_table(ds.table)} WHERE {where} ORDER BY {order}", params, limit)
            out.append({"table": ds.table, "description": ds.description, "columns": columns,
                        "rows": [dict(zip(columns, (_text(v) for v in r))) for r in rows]})
        return out

    def _run(self, sql: str, params: dict[str, str], limit: int) -> tuple[list[str], list[tuple]]:
        needed = set(_PLACEHOLDER.findall(sql))
        missing = needed - set(params)
        if missing:
            raise AttachmentError(f"SQL references unknown placeholder(s): {', '.join(sorted(missing))}; "
                                  f"available: {', '.join(sorted(params))}")
        return self.source.query_params(sql, {k: v for k, v in params.items() if k in needed}, limit)


def _text(v):
    return None if v is None else str(v)
