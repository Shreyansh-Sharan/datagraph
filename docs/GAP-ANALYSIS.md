# Gap analysis — ontoforge vs OntoBricks 0.8

**Date:** 2026-09-20 · **Source of comparison:** OntoBricks public docs (`docs/features.md`, `docs/user-guide.md`) only — the
reference code was never consulted for this (clean-room rule R1).

Legend: ✅ have · 🟡 partial · ❌ missing · ➖ not planned (UI-only or Databricks-proprietary coupling)

## 1. Ontology design
| Capability | Status | Note |
|---|---|---|
| Classes, subclass hierarchy, object/datatype properties, domain/range, inverse | ✅ | `ontology/` |
| OWL Turtle generation / OWL & RDFS import | ✅ | `to_turtle`, `from_rdf` |
| Property characteristics (functional, transitive, symmetric, asymmetric, irreflexive) | ❌ | model can't express them; OWL RL would use them |
| Cardinality / value restrictions on classes | ❌ | |
| Axioms: equivalent, disjoint, union, intersection, property chains, disjoint properties | ❌ | |
| SWRL rules (author, import/export .swrl, compile to SQL, evaluate) | ❌ | biggest single gap in reasoning |
| SHACL shapes authored by users (6 categories, severity, messages, conditional IF rules, Turtle import) | 🟡 | shapes are only auto-generated from the ontology |
| Ontology pitfalls detector (19 checks) | 🟡 | 7 structural checks; D2KLab (Apache-2.0) can be added as-is |
| Industry ontologies: FIBO, CDISC, IOF, HL7 FHIR | ❌ | verify each vocabulary's licence before bundling |
| LLM ontology wizard (metadata + guidelines templates + document enrichment) | 🟡 | draft from metadata + description; no templates, no PDF/DOCX enrichment |
| LLM ontology assistant (NL edits) | ✅ | |
| Auto icon assignment, dashboard mapping, OntoViz canvas, D3 designer | ➖ | UI / Databricks dashboards |

## 2. Metadata & mapping
| Capability | Status | Note |
|---|---|---|
| Catalog introspection (tables, columns, types, PK, FK) | ✅ | Postgres live; Databricks via information_schema (fakes only) |
| Metadata snapshot: import, refresh with change review, comment editing, source removal with dependency check | ✅ | `metadata.py` (2026-09-20) |
| Schema-drift detection (renamed/dropped columns vs stored mapping) | ✅ | `/mapping/drift`, recorded as a build step |
| Class→table / attribute→column mapping, key columns, IRI templates | ✅ | `MappingSpec` |
| Relationship via FK, link table, self-reference | ✅ | join-free compile |
| Relationship direction: reverse / bidirectional | ❌ | forward only |
| Per-attribute include/exclude, completion %, partial-mapping status, gap report | ❌ | |
| SQL query test / preview with row limit | ❌ | easy: compile one class, `LIMIT n` |
| LLM auto-map | 🟡 | single-shot suggest; no batch progress, cancel, agent log, re-assign-missing |
| Metadata quality warning (missing comments) | 🟡 | comments are captured; no warning surfaced yet |
| R2RML generation | ✅ | |
| R2RML import into the mapping spec | 🟡 | raw R2RML builds, but isn't lifted into `MappingSpec` |
| Rule-based autodraft from PK/FK (no LLM) | ✅ | **not in OntoBricks** |

## 3. Build & storage
| Capability | Status | Note |
|---|---|---|
| Build pipeline with per-step timings, run history, failure rollback | ✅ | |
| Async builds (background task, progress, cancel, navigate away) | ✅ | `BuildScheduler` |
| Postgres triple store | ✅ | |
| Delta view / table in the warehouse (two-layer model) | ✅ | `PublishConfig`; Databricks path verified with a fake connection only |
| Materialization modes (TABLE vs VIEW), Liquid Clustering / OPTIMIZE | 🟡 | view/table modes; no clustering/OPTIMIZE |
| Neo4j backend | ❌ | |
| Lakebase `managed_synced`, Lakeflow jobs, UC Volumes storage | ➖ | Databricks-proprietary |
| Freshness / last-updated indicator | 🟡 | build-run timestamps only |
| Triples grid (paged browsing of raw triples) | ❌ | trivial endpoint |

## 4. Exploration & analytics
| Capability | Status | Note |
|---|---|---|
| Search, entity detail, N-hop neighbourhood, type/predicate inventory | ✅ | |
| Community detection: Louvain, Label Propagation, Greedy Modularity | ❌ | `networkx` — small |
| Centrality analytics: PageRank, betweenness, degree, closeness, clustering coefficient; histograms, ranking, sampling | ❌ | `networkx` in-process; their Lakeflow job is ➖ |
| Data-model health (flat / time-series entity types) | ❌ | |
| AI graph interpretation (Key findings / notable entities / recommendations) | ❌ | fits the `LLMProvider` port |
| Cohorts (criteria → materialised group, explainable) | ❌ | |
| Bridges (cross-domain links) | ❌ | |
| Datasets (link a table/view to a class, preview rows) | ❌ | |
| Class actions / virtual attributes (SQL functions on an entity) | ❌ | generalise from UC functions to any SQL function |
| Sigma.js viewer, cluster collapse, dashboards embedding | ➖ | UI |

## 5. Reasoning & data quality
| Capability | Status | Note |
|---|---|---|
| OWL 2 RL closure, inferred layer, purge | ✅ | purge has no endpoint yet |
| SHACL validation | 🟡 | in-memory pySHACL only — won't scale; theirs compiles shapes to SQL |
| SWRL evaluation (violations + materialisation) | ❌ | |
| Graph reasoning (transitive closure, symmetric expansion) | 🟡 | OWL RL does it once characteristics exist in the model |
| Quality checks with generated SQL: cardinality, value constraints, property characteristics, global rules (labels, orphans) | ❌ | |
| Async execution with progress | ❌ | |

## 6. Query & integration
| Capability | Status | Note |
|---|---|---|
| GraphQL auto-schema, nested traversal, SDL | ✅ | |
| Pagination (offset), configurable depth, batch resolution (N+1), schema cache invalidation | 🟡 | limit only; per-request rebuild; N+1 resolvers |
| GraphiQL playground | ➖ | UI |
| MCP: list_domains, describe_ontology, search, describe_entity, graph_status, GraphQL tools | ✅ | |
| MCP: select_domain session, list_domain_versions, get_design_status, get_entity_context, invoke_entity_action | ❌ | |
| MCP: per-domain tool policy (Preferred / Normal / Disabled), hot switch | ❌ | |
| MCP: Streamable HTTP transport | 🟡 | stdio only wired |

## 7. Governance & administration
| Capability | Status | Note |
|---|---|---|
| Versions, DRAFT→IN_REVIEW→PUBLISHED, quorum, lease, audit | ✅ | |
| Active-version pinning (which version API/MCP serve) | ❌ | we serve latest published |
| Comments / discussion on a version | ❌ | |
| My Tasks cross-domain worklist, readiness cockpit | ❌ | readiness is computable today |
| Admin lock view, force unlock endpoint | 🟡 | `force=True` exists; no admin listing |
| Authentication & roles (Builder / Reviewer / Admin) | ✅ | header or API-key modes; viewer/builder/reviewer/admin |
| CSRF / secure cookies | ❌ | |
| Global settings store (warehouse, TTL, branding, connections) | ❌ | env-only |
| Lakehouse health / permission diagnostics | ❌ | |
| OBX export/import: multi-version modes, conflict resolution | 🟡 | one version, rename only |
| Structured JSON logging, request timing | ✅ | |
| Databricks Apps / DAB packaging, Dockerfile | ❌ | |

## Rough coverage
Backend-only surface (excluding UI and Databricks-proprietary items): roughly **half** done. Including UI: ~40%.

## Recommended order
**P1 — foundations the rest depends on:** ~~auth + roles · async builds · structured logging · run the Delta view/table DDL in Databricks · metadata snapshot + drift detection~~ — **done 2026-09-20**.
**P2 — parity on the core:** property characteristics & axioms → OWL RL · SWRL (parse + compile to SQL on the existing compiler) · user-authored SHACL compiled to SQL · quality checks · community detection + centralities · relationship direction · mapping completeness/exclusions · MCP parity + HTTP transport · comments · active-version pinning.
**P3 — ecosystem:** industry ontologies (licence check each) · Neo4j · cohorts · bridges · datasets · SQL-function actions/virtual attributes · D2KLab pitfalls · AI interpretation · richer bundles · Databricks Apps packaging.
**Skip:** OntoViz/sigma UI (own UI later), dashboards, Lakebase sync, Lakeflow analytics, UC Volumes, branding.
