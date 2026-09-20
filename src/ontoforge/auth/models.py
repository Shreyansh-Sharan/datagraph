from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class Role(str, Enum):
    VIEWER = "viewer"
    BUILDER = "builder"
    REVIEWER = "reviewer"
    ADMIN = "admin"

    @property
    def rank(self) -> int:
        return _RANK[self]

    def allows(self, required: Role) -> bool:
        return self.rank >= required.rank


_RANK = {Role.VIEWER: 0, Role.BUILDER: 1, Role.REVIEWER: 2, Role.ADMIN: 3}


class AuthError(Exception):
    """No usable identity (HTTP 401)."""


class Forbidden(Exception):
    """Identity known, role insufficient (HTTP 403)."""


@dataclass(frozen=True)
class Principal:
    name: str
    role: Role

    def require(self, role: Role) -> None:
        if not self.role.allows(role):
            raise Forbidden(f"{self.name} is {self.role.value}; this action needs {role.value}")


@dataclass(frozen=True)
class ApiKey:
    id: UUID
    name: str
    principal: str
    role: Role
    created_at: datetime
    revoked_at: datetime | None
    secret: str | None = None  # only populated at creation time
