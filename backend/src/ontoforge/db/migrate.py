"""Plain-SQL migrations applied in filename order, tracked in ``schema_migrations``."""
from __future__ import annotations

from pathlib import Path

from .connection import Database

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def applied_migrations(db: Database) -> list[str]:
    with db.transaction() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        return [r[0] for r in cur.execute("SELECT name FROM schema_migrations ORDER BY name")]


def run_migrations(db: Database) -> list[str]:
    done = set(applied_migrations(db))
    newly = []
    for path in migration_files():
        if path.name in done:
            continue
        with db.transaction() as cur:
            cur.execute(path.read_text())
            cur.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
        newly.append(path.name)
    return newly
