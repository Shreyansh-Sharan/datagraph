from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from uuid import UUID


class Status(str, Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    PUBLISHED = "published"
    ARCHIVED = "archived"


# Legal lifecycle moves. Publishing additionally needs the domain's review quorum.
TRANSITIONS: dict[Status, set[Status]] = {
    Status.DRAFT: {Status.IN_REVIEW},
    Status.IN_REVIEW: {Status.DRAFT, Status.PUBLISHED},
    Status.PUBLISHED: {Status.ARCHIVED},
    Status.ARCHIVED: set(),
}


class RegistryError(Exception):
    pass


class NotFound(RegistryError):
    pass


class LifecycleError(RegistryError):
    pass


class LockedError(RegistryError):
    pass


@dataclass(frozen=True)
class Domain:
    id: UUID
    name: str
    description: str | None
    base_iri: str
    review_quorum: int
    created_at: datetime
    mcp_policy: dict = field(default_factory=lambda: {"exposed": True})
    active_version_id: UUID | None = None
    ai_connection_id: UUID | None = None     # AI provider for drafts/assist; required once the connection module is configured
    sources: list[dict] = field(default_factory=list)   # [{connection_id, catalog, schemas}], the first is the primary
    materialization: str = "none"            # none | view | table
    target_schema: str | None = None

    # The primary source, as the single-source API and screens still read it.
    @property
    def primary(self) -> dict:
        return self.sources[0] if self.sources else {"connection_id": None, "catalog": None, "schemas": []}

    @property
    def connection_id(self) -> str | None:
        return self.primary.get("connection_id") or None

    @property
    def default_catalog(self) -> str | None:
        return self.primary.get("catalog") or None

    @property
    def schemas(self) -> list[str]:
        return list(self.primary.get("schemas") or [])

    @property
    def default_schema(self) -> str | None:
        return self.schemas[0] if self.schemas else None

    @property
    def mcp_exposed(self) -> bool:
        return bool(self.mcp_policy.get("exposed", True))

    def tool_disabled(self, tool: str) -> bool:
        return tool in self.mcp_policy.get("disabled_tools", [])


@dataclass(frozen=True)
class DomainVersion:
    id: UUID
    domain_id: UUID
    version: int
    status: Status
    ontology_ttl: str | None
    mapping: dict | None
    r2rml_ttl: str | None
    rules: dict | None
    quality: dict | None
    attachments: dict | None
    editor: str | None
    lease_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Review:
    id: int
    domain_version_id: UUID
    reviewer: str
    approved: bool
    comment: str | None
    review_round: int
    created_at: datetime


@dataclass(frozen=True)
class BuildRun:
    id: UUID
    domain_version_id: UUID
    status: str
    actor: str | None
    started_at: datetime
    finished_at: datetime | None
    triple_count: int | None
    error: str | None
    steps: list


@dataclass(frozen=True)
class Comment:
    id: int
    domain_version_id: UUID
    author: str
    body: str
    created_at: datetime


@dataclass(frozen=True)
class Task:
    domain: str
    version_id: UUID
    version: int
    status: Status
    editor: str | None = None
    approvals: int = 0
    quorum: int = 1


@dataclass(frozen=True)
class Lock:
    domain: str
    version_id: UUID
    version: int
    status: Status
    editor: str
    lease_expires_at: datetime | None
    stale: bool


@dataclass(frozen=True)
class AnalyticsRun:
    id: UUID
    domain_version_id: UUID
    scope: str
    status: str
    actor: str | None
    started_at: datetime
    finished_at: datetime | None
    nodes: int | None
    edges: int | None
    components: int | None
    avg_degree: float | None
    density: float | None
    duration_seconds: float | None
    error: str | None
    results: dict | None


@dataclass(frozen=True)
class AuditEntry:
    id: int
    domain_version_id: UUID | None
    actor: str | None
    action: str
    detail: dict | None
    created_at: datetime


DOMAIN_SETTINGS = ("description", "review_quorum", "base_iri", "ai_connection_id", "sources", "materialization", "target_schema")
MATERIALIZATIONS = ("none", "view", "table")
