"""Source-table metadata snapshots per domain version, and schema-drift detection.

A snapshot records what the mapping was designed against (columns, types, keys, comments).
``refresh`` re-reads the catalog and reports what changed; ``drift`` compares the mapping spec
against the snapshot and the live catalog so renamed or dropped columns are caught before a
build breaks.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ontoforge.catalog import CatalogAdapter
from ontoforge.db import Database
from ontoforge.mapping import MappingSpec
from ontoforge.ontology import Ontology
from ontoforge.registry import Registry


class MetadataError(ValueError):
    pass


@dataclass(frozen=True)
class TableSnapshot:
    table: str
    comment: str | None
    columns: list[dict]          # [{name, type, comment}]
    primary_key: list[str]
    foreign_keys: list[dict]     # [{columns, references, referenced_columns}]
    captured_at: datetime | None = None

    def column(self, name: str) -> dict | None:
        return next((c for c in self.columns if c["name"].lower() == name.lower()), None)


@dataclass
class RefreshChange:
    table: str
    missing: bool = False
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    modified: list[dict] = field(default_factory=list)   # [{column, from, to}]
    keys_changed: bool = False

    @property
    def changed(self) -> bool:
        return self.missing or bool(self.added or self.removed or self.modified or self.keys_changed)


@dataclass(frozen=True)
class DriftIssue:
    kind: str            # missing-table | missing-column | type-changed
    table: str
    column: str | None
    detail: str
    mapping_ref: str     # which class/relation/attribute depends on it
    severity: str = "error"


class MetadataService:
    def __init__(self, registry: Registry, catalog: CatalogAdapter, db: Database) -> None:
        self.registry, self.catalog, self.db = registry, catalog, db

    # -- snapshots -----------------------------------------------------------

    def import_tables(self, version_id: UUID, tables: list[str], *, actor: str, schema: str | None = None) -> list[TableSnapshot]:
        self.registry.assert_editable(version_id, actor)
        out = [self._capture(t) for t in tables]
        for snap in out:
            self._save(version_id, snap)
        return out

    def list(self, version_id: UUID) -> list[TableSnapshot]:
        with self.db.connection() as conn:
            rows = conn.cursor(row_factory=dict_row).execute(
                "SELECT * FROM metadata_snapshots WHERE domain_version_id = %s ORDER BY table_name", (version_id,)).fetchall()
        return [_snapshot(r) for r in rows]

    def get(self, version_id: UUID, table: str) -> TableSnapshot:
        with self.db.connection() as conn:
            row = conn.cursor(row_factory=dict_row).execute(
                "SELECT * FROM metadata_snapshots WHERE domain_version_id = %s AND table_name = %s", (version_id, table)).fetchone()
        if row is None:
            raise MetadataError(f"No snapshot of table {table!r} in this version")
        return _snapshot(row)

    def refresh(self, version_id: UUID, *, actor: str) -> list[RefreshChange]:
        self.registry.assert_editable(version_id, actor)
        changes = []
        for old in self.list(version_id):
            change = RefreshChange(table=old.table)
            try:
                new = self._capture(old.table)
            except Exception:  # noqa: BLE001 - table gone or unreadable
                change.missing = True
                changes.append(change)
                continue
            old_cols = {c["name"].lower(): c for c in old.columns}
            new_cols = {c["name"].lower(): c for c in new.columns}
            change.added = [c["name"] for k, c in new_cols.items() if k not in old_cols]
            change.removed = [c["name"] for k, c in old_cols.items() if k not in new_cols]
            change.modified = [{"column": c["name"], "from": old_cols[k]["type"], "to": c["type"]}
                               for k, c in new_cols.items() if k in old_cols and old_cols[k]["type"] != c["type"]]
            change.keys_changed = (old.primary_key, old.foreign_keys) != (new.primary_key, new.foreign_keys)
            # keep comments a user wrote (or that the catalog no longer carries)
            merged = [{**c, "comment": c["comment"] or (old_cols.get(c["name"].lower()) or {}).get("comment")} for c in new.columns]
            self._save(version_id, TableSnapshot(new.table, new.comment or old.comment, merged, new.primary_key, new.foreign_keys))
            if change.changed:
                changes.append(change)
        return changes

    def set_comment(self, version_id: UUID, table: str, column: str | None, comment: str | None, *, actor: str) -> TableSnapshot:
        self.registry.assert_editable(version_id, actor)
        snap = self.get(version_id, table)
        if column is None:
            snap = TableSnapshot(snap.table, comment, snap.columns, snap.primary_key, snap.foreign_keys)
        else:
            if snap.column(column) is None:
                raise MetadataError(f"Table {table!r} has no column {column!r}")
            cols = [{**c, "comment": comment} if c["name"].lower() == column.lower() else c for c in snap.columns]
            snap = TableSnapshot(snap.table, snap.comment, cols, snap.primary_key, snap.foreign_keys)
        self._save(version_id, snap)
        return snap

    def remove(self, version_id: UUID, table: str, *, actor: str) -> None:
        version = self.registry.assert_editable(version_id, actor)
        users = [ref for t, ref in _mapping_tables(version.mapping) if t.lower() == table.lower()]
        if users:
            raise MetadataError(f"Table {table!r} is used by the mapping: {', '.join(users)}")
        with self.db.transaction() as cur:
            cur.execute("DELETE FROM metadata_snapshots WHERE domain_version_id = %s AND table_name = %s", (version_id, table))

    # -- drift ---------------------------------------------------------------

    def drift(self, version_id: UUID) -> list[DriftIssue]:
        version = self.registry.get_version(version_id)
        if not version.mapping:
            return []
        spec = MappingSpec.from_dict(version.mapping)
        snapshots = {s.table.lower(): s for s in self.list(version_id)}
        issues: list[DriftIssue] = []
        live_cache: dict[str, dict[str, dict] | None] = {}

        def live(table: str) -> dict[str, dict] | None:
            key = table.lower()
            if key not in live_cache:
                try:
                    live_cache[key] = {c["name"].lower(): c for c in self.catalog.column_details(table)} or None
                except Exception:  # noqa: BLE001
                    live_cache[key] = None
            return live_cache[key]

        for table, ref, columns in _mapping_columns(spec):
            cols = live(table)
            if cols is None:
                issues.append(DriftIssue("missing-table", table, None, f"Table {table} is not in the catalog", ref))
                continue
            snap = snapshots.get(table.lower())
            for col in columns:
                if col.lower() not in cols:
                    issues.append(DriftIssue("missing-column", table, col, f"Column {table}.{col} is not in the catalog", ref))
                elif snap and (old := snap.column(col)) and old["type"] != cols[col.lower()]["type"]:
                    issues.append(DriftIssue("type-changed", table, col, f"{old['type']} -> {cols[col.lower()]['type']}", ref, "warning"))
        return _dedupe(issues)

    # -- internals -----------------------------------------------------------

    def _capture(self, table: str) -> TableSnapshot:
        columns = self.catalog.column_details(table)
        if not columns:
            raise MetadataError(f"Table {table!r} not found in the catalog")
        return TableSnapshot(table, self.catalog.table_comment(table), columns, list(self.catalog.primary_key(table)),
                             [{"columns": list(c), "references": r, "referenced_columns": list(rc)} for c, r, rc in self.catalog.foreign_keys(table)])

    def _save(self, version_id: UUID, snap: TableSnapshot) -> None:
        with self.db.transaction() as cur:
            cur.execute(
                "INSERT INTO metadata_snapshots (domain_version_id, table_name, comment, columns, primary_key, foreign_keys) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (domain_version_id, table_name) DO UPDATE SET comment = EXCLUDED.comment, "
                "columns = EXCLUDED.columns, primary_key = EXCLUDED.primary_key, foreign_keys = EXCLUDED.foreign_keys, captured_at = now()",
                (version_id, snap.table, snap.comment, Jsonb(snap.columns), Jsonb(snap.primary_key), Jsonb(snap.foreign_keys)))


def _snapshot(row: dict) -> TableSnapshot:
    return TableSnapshot(row["table_name"], row["comment"], row["columns"], row["primary_key"], row["foreign_keys"], row["captured_at"])


def _mapping_columns(spec: MappingSpec):
    """(table, mapping reference, columns) for everything the mapping reads."""
    by_class = {c.class_iri: c for c in spec.classes}
    for c in spec.classes:
        if c.table:
            name = Ontology.local_name(c.class_iri)
            yield c.table, f"class {name}", list(c.key_columns) + [a.column for a in c.attributes]
    for r in spec.relations:
        src = by_class.get(r.source_class)
        table = r.table or (src.table if src else None)
        if table:
            yield table, f"relation {Ontology.local_name(r.property_iri)}", list(r.source_key or ()) + list(r.target_key or ())


def _mapping_tables(mapping: dict | None):
    if not mapping:
        return []
    return [(t, ref) for t, ref, _ in _mapping_columns(MappingSpec.from_dict(mapping))]


def _dedupe(issues: list[DriftIssue]) -> list[DriftIssue]:
    seen, out = set(), []
    for i in issues:
        key = (i.kind, i.table.lower(), (i.column or "").lower(), i.mapping_ref)
        if key not in seen:
            seen.add(key)
            out.append(i)
    return out


def snapshot_to_table_meta(snap: TableSnapshot, samples: list | None = None) -> dict:
    return {"table": snap.table, "comment": snap.comment, "columns": snap.columns, "primary_key": snap.primary_key,
            "foreign_keys": snap.foreign_keys, "samples": samples or []}
