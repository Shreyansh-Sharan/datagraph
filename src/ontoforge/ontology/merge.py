"""Merging external ontologies into a version's ontology, and the industry-ontology catalogue."""
from __future__ import annotations

from .model import Ontology

# Sources a client may import by name. Every entry carries its licence: check it before bundling
# or redistributing terms, and never assume a vocabulary is free because it is public.
INDUSTRY_ONTOLOGIES: dict[str, dict] = {
    "fibo": {"name": "FIBO — Financial Industry Business Ontology (EDM Council)", "licence": "MIT",
             "url": "https://spec.edmcouncil.org/fibo/ontology/master/latest/prod.fibo-quickstart.ttl", "format": "turtle",
             "notes": "Large (tens of thousands of terms); import a module-specific file for smaller graphs."},
    "fhir": {"name": "HL7 FHIR RDF (R5)", "licence": "CC0 1.0 (FHIR specification); HL7 trademarks apply",
             "url": "https://build.fhir.org/fhir.ttl", "format": "turtle",
             "notes": "The R5 core ontology; resource-specific shapes are separate files."},
    "iof": {"name": "IOF Core — Industrial Ontologies Foundry", "licence": "BSD-3-Clause (IOF licence)",
            "url": "https://spec.industrialontologies.org/ontology/core/Core/", "format": "turtle",
            "notes": "Core module; Maintenance and Supply Chain modules are published alongside."},
    "schema": {"name": "schema.org", "licence": "CC BY-SA 3.0",
               "url": "https://schema.org/version/latest/schemaorg-current-https.ttl", "format": "turtle",
               "notes": "General-purpose vocabulary; attribution required."},
    "cdisc": {"name": "CDISC controlled terminology / SDTM", "licence": "CDISC terms of use — acceptance required; not fetched automatically",
              "url": None, "format": None,
              "notes": "Download from CDISC after accepting their terms, then import the file with data/format."},
}


def merge_ontologies(base: Ontology, incoming: Ontology) -> tuple[Ontology, dict]:
    """Add everything from ``incoming`` that ``base`` lacks. Existing terms in ``base`` win."""
    merged = Ontology.from_dict(base.to_dict())
    report = {"classes_added": 0, "classes_skipped": 0, "properties_added": 0, "properties_skipped": 0}
    for c in incoming.classes.values():
        if c.iri in merged.classes:
            report["classes_skipped"] += 1
        else:
            merged.add_class(c)
            report["classes_added"] += 1
    for p in incoming.all_properties():
        if merged.property(p.iri) is not None:
            report["properties_skipped"] += 1
            continue
        (merged.add_object_property if p.__class__.__name__ == "ObjectProperty" else merged.add_datatype_property)(p)
        report["properties_added"] += 1
    return merged, report
