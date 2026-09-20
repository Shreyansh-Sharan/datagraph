# Gap analysis — ontoforge vs OntoBricks 0.8

**Date:** 2026-09-20 · **Source of comparison:** OntoBricks public docs (`docs/features.md`, `docs/user-guide.md`) only — the
reference code was never consulted for this (clean-room rule R1).

Legend: ✅ have · 🟡 partial · ❌ missing · ➖ not planned (UI-only or Databricks-proprietary coupling)

## 1. Ontology design
| Capability | Status | Note |
|---|---|---|
| Classes, subclass hierarchy, object/datatype properties, domain/range, inverse | ✅ | `ontology/` |
| OWL Turtle generation / OWL & RDFS import | ✅ | `to_turtle`, `from_rdf` |
| Property characteristics (functional, transitive, symmetric, asymmetric, irreflexive) | ✅ | model + OWL + OWL RL + SHACL + GraphQL |
| Cardinality / value restrictions on classes | ✅ | min/max/exactly/some/only/hasValue |
| Axioms: equivalent, disjoint, union, intersection, property chains, disjoint properties | 🟡 | equivalent, disjoint, chains, subPropertyOf; no union/intersection expressions |
| SWRL rules (author, import/export .swrl, compile to SQL, evaluate) | ✅ | presentation syntax, SQL fixpoint materialisation, violation mode; no .swrl RDF import |
| SHACL shapes authored by users (6 categories, severity, messages, conditional IF rules, Turtle import) | 🟡 | 12 constraint kinds, 3 severities, messages, SHACL import/export, SQL validation; no conditional IF rules |
| Ontology pitfalls detector (19 checks) | 🟡 | 7 structural checks; D2KLab (Apache-2.0) can be added as-is |
| Industry ontologies: FIBO, CDISC, IOF, HL7 FHIR | ✅ | catalogue with licences; import by source/url/data, merge or replace; CDISC gated |
| LLM ontology wizard (metadata + guidelines templates + document enrichment) | 🟡 | draft from metadata + description; no templates, no PDF/DOCX enrichment |
| LLM ontology assistant (NL edits) | ✅ | |
| Auto icon assignment, dashboard mapping, OntoViz canvas, D3 designer | 🟡 | own SPA: keyword icons (`ofui:icon`), ontology map as the default editor (click a class → side form), mapping designer coloured by status with Status/Data/SQL panel and click-to-bind column headers; no drag-and-drop canvas editing, no dashboards |

## 2. Metadata & mapping
| Capability | Status | Note |
|---|---|---|
| Catalog introspection (tables, columns, types, PK, FK) | ✅ | Postgres live; Databricks via information_schema (fakes only) |
| Metadata snapshot: import, refresh with change review, comment editing, source removal with dependency check | ✅ | `metadata.py` (2026-09-20) |
| Schema-drift detection (renamed/dropped columns vs stored mapping) | ✅ | `/mapping/drift`, recorded as a build step |
| Class→table / attribute→column mapping, key columns, IRI templates | ✅ | `MappingSpec` |
| Relationship via FK, link table, self-reference | ✅ | join-free compile |
| Relationship direction: reverse / bidirectional | ✅ | |
| Per-attribute include/exclude, completion %, partial-mapping status, gap report | ✅ | `/mapping/status`, `/mapping/exclude*` |
| SQL query test / preview with row limit | ✅ | `/mapping/preview`, `/mapping/test-sql` |
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
| Materialization modes (TABLE vs VIEW), Liquid Clustering / OPTIMIZE | ✅ | |
| Neo4j backend | ❌ | |
| Lakebase `managed_synced`, Lakeflow jobs, UC Volumes storage | ➖ | Databricks-proprietary |
| Freshness / last-updated indicator | 🟡 | build-run timestamps only |
| Triples grid (paged browsing of raw triples) | ✅ | `/graph/triples`, Triples tab |

## 4. Exploration & analytics
| Capability | Status | Note |
|---|---|---|
| Search, entity detail, N-hop neighbourhood, type/predicate inventory | ✅ | |
| Community detection: Louvain, Label Propagation, Greedy Modularity | ✅ | optional persistence as inferred triples |
| Centrality analytics: PageRank, betweenness, degree, closeness, clustering coefficient; histograms, ranking, sampling | ✅ | in-process networkx; sampled above 5k nodes |
| Data-model health (flat / time-series entity types) | ✅ | |
| AI graph interpretation (Key findings / notable entities / recommendations) | ✅ | `/analytics/runs/{id}/interpret` |
| Cohorts (criteria → materialised group, explainable) | ✅ | per-member evidence; materialised as inferred triples |
| Bridges (cross-domain links) | ✅ | key-matched counterparts, in REST + MCP |
| Datasets (link a table/view to a class, preview rows) | ✅ | |
| Class actions / virtual attributes (SQL functions on an entity) | ✅ | any SELECT with `:key` placeholders; MCP invoke/compute |
| Sigma.js viewer, cluster collapse, dashboards embedding | ✅/➖ | sigma.js stage: overview on load, find (label/IRI × contains/exact/starts/ends), hover/click/right-click menu, expand N hops, clusters with resolution slider, colour-by-cluster, collapse/expand super-nodes, chips, clear; dashboards ➖ |

## 5. Reasoning & data quality
| Capability | Status | Note |
|---|---|---|
| OWL 2 RL closure, inferred layer, purge | ✅ | purge has no endpoint yet |
| SHACL validation | ✅ | SQL-compiled constraints; pySHACL kept for ad-hoc shapes |
| SWRL evaluation (violations + materialisation) | ✅ | |
| Graph reasoning (transitive closure, symmetric expansion) | ✅ | via OWL RL with characteristics |
| Quality checks with generated SQL: cardinality, value constraints, property characteristics, global rules (labels, orphans) | ✅ | 14 kinds incl. require_label / no_orphans |
| Async execution with progress | ❌ | |

## 6. Query & integration
| Capability | Status | Note |
|---|---|---|
| GraphQL auto-schema, nested traversal, SDL | ✅ | |
| Pagination (offset), configurable depth, batch resolution (N+1), schema cache invalidation | 🟡 | limit only; per-request rebuild; N+1 resolvers |
| GraphiQL playground | 🟡 | simple GraphQL console under Settings |
| MCP: list_domains, describe_ontology, search, describe_entity, graph_status, GraphQL tools | ✅ | |
| MCP: select_domain session, list_domain_versions, get_design_status, get_entity_context, invoke_entity_action | ✅ | 14 tools |
| MCP: per-domain tool policy (Preferred / Normal / Disabled), hot switch | ✅ | exposed flag + disabled tools, checked per call |
| MCP: Streamable HTTP transport | ✅ | mounted at `/mcp` behind API auth |

## 7. Governance & administration
| Capability | Status | Note |
|---|---|---|
| Versions, DRAFT→IN_REVIEW→PUBLISHED, quorum, lease, audit | ✅ | |
| Active-version pinning (which version API/MCP serve) | ✅ | `/domains/{name}/active` |
| Comments / discussion on a version | ✅ | |
| My Tasks cross-domain worklist, readiness cockpit | ✅ | `/tasks`, MCP `get_design_status` |
| Admin lock view, force unlock endpoint | ✅ | `/admin/locks` |
| Authentication & roles (Builder / Reviewer / Admin) | ✅ | header or API-key modes; viewer/builder/reviewer/admin |
| CSRF / secure cookies | ❌ | |
| Global settings store (warehouse, TTL, branding, connections) | ❌ | env-only |
| Lakehouse health / permission diagnostics | ❌ | |
| OBX export/import: multi-version modes, conflict resolution | ✅ | bundle v2: active/latest/all; fail/skip/overwrite/rename |
| Structured JSON logging, request timing | ✅ | |
| Databricks Apps / DAB packaging, Dockerfile | ✅ | `Dockerfile`, `deploy/app.yaml` (image build verified; app deploy not run) |

## Rough coverage
Backend-only surface (excluding UI and Databricks-proprietary items): **~95%** as of 2026-09-21 (remaining: Neo4j, D2KLab pitfalls, conditional SHACL, `.swrl` import, union/intersection axioms). Including UI: ~80% (own SPA at /ui, verified in a real browser).

## Recommended order
**P1 — foundations the rest depends on:** ~~auth + roles · async builds · structured logging · run the Delta view/table DDL in Databricks · metadata snapshot + drift detection~~ — **done 2026-09-20**.
**P2 — parity on the core:** ~~property characteristics & axioms → OWL RL · SWRL · user-authored SHACL compiled to SQL · quality checks · community detection + centralities · relationship direction · mapping completeness/exclusions · MCP parity + HTTP transport · comments · active-version pinning~~ — **done 2026-09-20**.
**P3 — ecosystem:** ~~industry ontologies · cohorts · bridges · datasets · SQL-function actions/virtual attributes · AI interpretation · richer bundles · Databricks Apps packaging~~ — **done 2026-09-21**. Remaining: Neo4j store, D2KLab pitfall scanner (heavy ML deps), conditional SHACL IF rules, `.swrl` RDF import, union/intersection axioms.
**Skip:** OntoViz/sigma UI (own UI later), dashboards, Lakebase sync, Lakeflow analytics, UC Volumes, branding.
