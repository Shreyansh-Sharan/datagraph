"""Export / import a domain as one JSON document, for moving domains between environments."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from ontoforge.registry import DomainVersion, Registry, Status

FORMAT = "ontoforge-bundle/1"


def export_bundle(registry: Registry, domain_name: str, version_id: UUID | None = None) -> dict:
    d = registry.get_domain(domain_name)
    v = registry.get_version(version_id) if version_id else \
        registry.latest_version(d.id, status=Status.PUBLISHED) or registry.latest_version(d.id)
    if v is None:
        raise ValueError(f"Domain {domain_name!r} has no versions to export")
    return {
        "format": FORMAT,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "domain": {"name": d.name, "description": d.description, "base_iri": d.base_iri, "review_quorum": d.review_quorum},
        "version": {"number": v.version, "status": v.status.value, "ontology_ttl": v.ontology_ttl,
                    "mapping": v.mapping, "r2rml_ttl": v.r2rml_ttl, "rules": v.rules, "quality": v.quality},
    }


def import_bundle(registry: Registry, bundle: dict, *, actor: str, name: str | None = None) -> DomainVersion:
    """Create the domain if needed, then a new draft holding the bundle's content."""
    if bundle.get("format") != FORMAT:
        raise ValueError(f"Unsupported bundle format {bundle.get('format')!r}; expected {FORMAT}")
    meta, content = bundle["domain"], bundle["version"]
    name = name or meta["name"]
    try:
        domain = registry.get_domain(name)
    except Exception:  # NotFound
        domain = registry.create_domain(name, meta.get("description"), base_iri=meta["base_iri"],
                                        review_quorum=meta.get("review_quorum", 1))
    version = registry.create_version(domain.id, actor=actor)
    return registry.update_content(version.id, actor=actor, ontology_ttl=content.get("ontology_ttl"),
                                   mapping=content.get("mapping"), r2rml_ttl=content.get("r2rml_ttl"), rules=content.get("rules"), quality=content.get("quality"))
