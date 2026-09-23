"""Export / import domains as one JSON document (format 2: any number of versions).

Import creates the domain when needed and appends the bundle's versions in order, preserving
each version's status (a published version stays published — bundles are how environments are
promoted). Conflicts on the domain name: fail (default) · skip · overwrite (append) · rename.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from ontoforge.registry import DomainVersion, NotFound, Registry, Status

FORMAT = "ontoforge-bundle/2"
FORMAT_V1 = "ontoforge-bundle/1"
CONTENT_KEYS = ("ontology_ttl", "mapping", "r2rml_ttl", "rules", "quality", "attachments")


@dataclass
class ImportResult:
    domain: str
    imported: list[int] = field(default_factory=list)   # bundle version numbers imported
    skipped: list[int] = field(default_factory=list)
    versions: list[DomainVersion] = field(default_factory=list)


def export_bundle(registry: Registry, domain_name: str, version_id: UUID | None = None, versions: str = "active") -> dict:
    d = registry.get_domain(domain_name)
    if version_id:
        chosen = [registry.get_version(version_id)]
    elif versions == "all":
        chosen = sorted(registry.list_versions(d.id), key=lambda v: v.version)
    elif versions == "latest":
        chosen = [registry.latest_version(d.id)]
    elif versions == "active":
        chosen = [registry.served_version(d.id)]
    else:
        raise ValueError("versions must be active, latest or all")
    chosen = [v for v in chosen if v is not None]
    if not chosen:
        raise ValueError(f"Domain {domain_name!r} has no versions to export")
    return {
        "format": FORMAT,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "domain": {"name": d.name, "description": d.description, "base_iri": d.base_iri, "review_quorum": d.review_quorum,
                   "mcp_policy": d.mcp_policy},
        "versions": [{"number": v.version, "status": v.status.value, **{k: getattr(v, k) for k in CONTENT_KEYS}} for v in chosen],
    }


def import_bundle(registry: Registry, bundle: dict, *, actor: str, name: str | None = None,
                  on_conflict: str = "fail") -> ImportResult:
    bundle = _normalise(bundle)
    if on_conflict not in ("fail", "skip", "overwrite", "rename"):
        raise ValueError("on_conflict must be fail, skip, overwrite or rename")
    meta = bundle["domain"]
    name = name or meta["name"]
    result = ImportResult(domain=name)
    existing = _find(registry, name)
    if existing is not None:
        if on_conflict == "fail":
            raise ValueError(f"Domain {name!r} already exists (use on_conflict=skip|overwrite|rename)")
        if on_conflict == "skip":
            result.skipped = [v["number"] for v in bundle["versions"]]
            return result
        if on_conflict == "rename":
            n = 2
            while _find(registry, f"{name}_{n}") is not None:
                n += 1
            name = result.domain = f"{name}_{n}"
            existing = None
    domain = existing or registry.create_domain(name, meta.get("description"), base_iri=meta["base_iri"],
                                                review_quorum=meta.get("review_quorum", 1))
    if meta.get("mcp_policy") and existing is None:
        registry.set_mcp_policy(domain.id, meta["mcp_policy"])
    for v in bundle["versions"]:
        status = Status(v.get("status", "draft"))
        content = {k: v.get(k) for k in CONTENT_KEYS}
        draft = registry.latest_version(domain.id, status=Status.DRAFT) if status is Status.DRAFT else None
        if draft is not None:
            if on_conflict == "overwrite":       # the domain's single draft takes the bundle's draft content
                imported = registry.update_content(draft.id, actor=actor, **{k: val for k, val in content.items() if val is not None})
            else:
                result.skipped.append(v["number"])
                continue
        else:
            imported = registry.import_version(domain.id, content, status, actor=actor)
        result.imported.append(v["number"])
        result.versions.append(imported)
    return result


def _normalise(bundle: dict) -> dict:
    fmt = bundle.get("format")
    if fmt == FORMAT:
        return bundle
    if fmt == FORMAT_V1:
        return {**bundle, "format": FORMAT, "versions": [bundle["version"]]}
    raise ValueError(f"Unsupported bundle format {fmt!r}; expected {FORMAT}")


def _find(registry: Registry, name: str):
    try:
        return registry.get_domain(name)
    except NotFound:
        return None
