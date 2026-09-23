"""A catalog adapter over a version's metadata snapshot: the columns, keys and foreign keys it
captured, without a round trip to the source. Drafting reads it when the snapshot holds the tables."""
from __future__ import annotations

from uuid import UUID

from .base import CatalogAdapter


class SnapshotCatalog(CatalogAdapter):
    def __init__(self, metadata, version_id: UUID) -> None:
        self.metadata, self.version_id = metadata, version_id
        self._snaps = {s.table.lower(): s for s in metadata.list(version_id)}

    def _snap(self, table: str):
        s = self._snaps.get(table.lower())
        if s is None:   # a bare name names the one table with that short name
            hits = [x for k, x in self._snaps.items() if k.rsplit(".", 1)[-1] == table.lower()]
            s = hits[0] if len(hits) == 1 else None
        return s

    def has(self, table: str) -> bool:
        return self._snap(table) is not None

    def qualified(self, table: str, schema: str | None = None) -> str:
        s = self._snap(table)
        return s.table if s else super().qualified(table, schema)

    def column_types(self, table: str) -> dict[str, str]:
        s = self._snap(table)
        return {c["name"]: c.get("type") or "" for c in s.columns} if s else {}

    def column_details(self, table: str) -> list[dict]:
        s = self._snap(table)
        return [{"name": c["name"], "type": c.get("type") or "", "comment": c.get("comment")} for c in s.columns] if s else []

    def table_comment(self, table: str) -> str | None:
        s = self._snap(table)
        return s.comment if s else None

    def primary_key(self, table: str) -> tuple[str, ...]:
        s = self._snap(table)
        return tuple(s.primary_key or ()) if s else ()

    def foreign_keys(self, table: str) -> list[tuple[tuple[str, ...], str, tuple[str, ...]]]:
        s = self._snap(table)
        return [(tuple(f["columns"]), self.qualified(f["references"], s.table.rsplit(".", 1)[0] if "." in s.table else None), tuple(f.get("referenced_columns") or ())) for f in (s.foreign_keys or [])] if s else []

    def list_tables(self, schema: str | None = None) -> list[str]:
        return sorted(s.table for s in self._snaps.values() if not schema or s.table.lower().startswith(schema.lower() + "."))

    def list_schemas(self, catalog: str | None = None) -> list[str]:
        return sorted({s.table.rsplit(".", 1)[0] for s in self._snaps.values() if "." in s.table})
