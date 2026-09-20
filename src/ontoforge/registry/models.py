from __future__ import annotations

from dataclasses import dataclass
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
