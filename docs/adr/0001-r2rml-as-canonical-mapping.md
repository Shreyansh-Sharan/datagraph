# ADR 0001 — R2RML is the canonical mapping format

**Status:** accepted · **Date:** 2026-09-20

## Decision
Mappings between tables and the ontology are stored and exchanged as W3C R2RML documents
(Turtle). The UI and LLM layers produce R2RML; the compiler consumes only R2RML.

## Sources
- W3C R2RML: RDB to RDF Mapping Language, Recommendation 27 Sep 2012 — https://www.w3.org/TR/r2rml/
- rdflib 7 documentation (parsing/serialising Turtle) — https://rdflib.readthedocs.io/

## Why
- Royalty-free open standard; portable across tools and warehouses.
- Fully specifies generated-triple semantics (§11), so compiler behaviour is testable against a
  public reference rather than an internal convention.
- Decouples authoring (UI/LLM) from execution (compiler): both sides target a stable document.

## Consequences
- Parser rejects documents violating R2RML structural constraints (`MappingError`).
- Serialiser emits explicit `rr:termType` so round-trips are lossless.
- Unsupported features (graph maps, inverse expressions) are documented in README until implemented.
