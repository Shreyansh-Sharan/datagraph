"""Principal roles and API keys, in Postgres. Keys are stored as SHA-256 hashes only."""
from __future__ import annotations

import hashlib
import secrets
from uuid import UUID

from psycopg.rows import dict_row

from ontoforge.db import Database

from .models import ApiKey, Role

KEY_PREFIX = "of_"


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class Principals:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- roles ---------------------------------------------------------------

    def set_role(self, name: str, role: Role) -> None:
        with self.db.transaction() as cur:
            cur.execute("INSERT INTO principals (name, role) VALUES (%s, %s) "
                        "ON CONFLICT (name) DO UPDATE SET role = EXCLUDED.role, updated_at = now()", (name, role.value))

    def get_role(self, name: str) -> Role | None:
        with self.db.transaction() as cur:
            row = cur.execute("SELECT role FROM principals WHERE name = %s", (name,)).fetchone()
        return Role(row[0]) if row else None

    def list_roles(self) -> list[dict]:
        with self.db.transaction() as cur:
            return [{"name": n, "role": r} for n, r in cur.execute("SELECT name, role FROM principals ORDER BY name")]

    def delete(self, name: str) -> None:
        with self.db.transaction() as cur:
            cur.execute("DELETE FROM principals WHERE name = %s", (name,))

    # -- api keys ------------------------------------------------------------

    def create_api_key(self, name: str, *, principal: str, role: Role) -> ApiKey:
        secret = KEY_PREFIX + secrets.token_urlsafe(32)
        with self.db.connection() as conn:
            row = conn.cursor(row_factory=dict_row).execute(
                "INSERT INTO api_keys (name, principal, role, key_hash) VALUES (%s, %s, %s, %s) RETURNING *",
                (name, principal, role.value, _hash(secret))).fetchone()
            conn.commit()
        return _key(row, secret)

    def resolve_api_key(self, secret: str) -> ApiKey | None:
        with self.db.connection() as conn:
            row = conn.cursor(row_factory=dict_row).execute(
                "SELECT * FROM api_keys WHERE key_hash = %s AND revoked_at IS NULL", (_hash(secret),)).fetchone()
        return _key(row) if row else None

    def revoke_api_key(self, key_id: UUID) -> None:
        with self.db.transaction() as cur:
            cur.execute("UPDATE api_keys SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL", (key_id,))

    def list_api_keys(self) -> list[ApiKey]:
        with self.db.connection() as conn:
            rows = conn.cursor(row_factory=dict_row).execute("SELECT * FROM api_keys ORDER BY created_at").fetchall()
        return [_key(r) for r in rows]


def _key(row: dict, secret: str | None = None) -> ApiKey:
    return ApiKey(id=row["id"], name=row["name"], principal=row["principal"], role=Role(row["role"]),
                  created_at=row["created_at"], revoked_at=row["revoked_at"], secret=secret)
