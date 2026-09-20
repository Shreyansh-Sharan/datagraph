# Clean-Room Rebuild Plan — Semantic Layer / Knowledge Graph Platform

**Status:** Draft for review
**Date:** 2026-09-20
**Reference system analysed:** `databrickslabs/ontobricks` v0.8.0 (~115k LOC Python, ~74k LOC JS)
**Purpose:** Build a commercially-ownable, multi-warehouse equivalent without inheriting the Databricks License.

> **Not legal advice.** This document records an engineering analysis and a risk-reduction
> methodology. Have counsel review Section 1 and Section 3 before commercial launch.

---

## 1. The licensing reality

OntoBricks does **not** ship under Apache-2.0, MIT, or any OSI-approved licence. It ships under the
bespoke **"Databricks License", Copyright (2024) Databricks, Inc.** (`LICENSE.txt`). This is a
proprietary, field-of-use-restricted licence. Reading it precisely matters, because it is more
permissive than people assume in one direction and far more dangerous in another.

### 1.1 What it actually permits

> "You may view, use, copy, modify, publish, and/or distribute the Licensed Materials **solely for
> the purposes of using the Licensed Materials within or connecting to the Databricks Services**."

So modification, redistribution, and even commercial use are permitted — *provided every use stays
tethered to Databricks*. For a Databricks-only internal deployment, forking is legally available today.

### 1.2 The five clauses that make it unusable for your product

| # | Clause | Consequence for you |
|---|--------|---------------------|
| **1** | **Field-of-use lock** — "You may not use the Licensed Materials except in connection with your use of the Databricks Services" | Your stated roadmap (Fabric, SQL Server, other warehouses) is **prohibited on day one**. A Fabric port of a derivative work is a breach, not a grey area. This alone settles the question. |
| **2** | **Termination at will** — "Databricks may terminate this license **at any time on notice**. Upon termination, you must permanently delete the Licensed Materials and all copies thereof." | No cause required. You cannot build a revenue-generating product on a licence that can be revoked unilaterally, forcing deletion of your codebase. This is commercially fatal. |
| **3** | **Viral attribution** — derivatives must carry this License, the `NOTICE` file, and all Databricks copyright/attribution notices | Your customers receive a **Databricks-licensed** product. They must themselves be Databricks customers under the MCSA to lawfully use it. You cannot licence it on your own terms. |
| **4** | **AS-IS + $1,000 liability cap** | You would be reselling software you are contractually unable to warrant, while carrying full downstream liability yourself. Enterprise procurement will reject this. |
| **5** | **Trademark** — the licence grants no trademark rights | "OntoBricks", the logo, the icon set, `ontobricks.org` branding are all off-limits regardless. |

### 1.3 Verdict

**Rebuild. Do not fork.** Clause 1 kills the multi-warehouse roadmap and Clause 2 kills the business
case. The good news, established in Section 2, is that the rebuild is dramatically cheaper than the
115k LOC figure suggests — because most of the genuinely hard logic is not Databricks' property.

*(Alternative worth one email: Databricks Labs projects sometimes relicense on request, and a
commercial OEM/relicensing conversation with Databricks is not unreasonable. Cost: one email. But
do not let it block the rebuild, and note it would still not give you Fabric rights.)*

---

## 2. What is actually protected vs. what is free

Copyright protects **expression**, not ideas, methods, architecture, or functionality. Applying that
split to this system is what makes the rebuild tractable.

### 2.1 Free — public standards (royalty-free, W3C)

The entire semantic core is open standards you can implement without permission:

| Standard | Role |
|---|---|
| **RDF 1.1** | Triple data model (subject, predicate, object) |
| **RDFS / OWL 2** | Ontology language — classes, properties, domain/range, hierarchy |
| **OWL 2 RL** | The rule-based profile used for deductive closure/inference |
| **R2RML** | W3C Recommendation for mapping relational DBs to RDF — `rr:TriplesMap`, `rr:logicalTable`, `rr:subjectMap`, `rr:predicateObjectMap` |
| **SPARQL 1.1** | RDF query language |
| **SHACL** | Shapes Constraint Language — data-quality validation |
| **SWRL** | Horn-clause rules |
| **MCP** | Model Context Protocol (Anthropic, open spec) |
| **GraphQL** | Open spec (Linux Foundation) |

**Nothing in the conceptual pipeline is proprietary.** "Map relational tables to RDF via R2RML,
materialise triples, reason with OWL 2 RL, query with SPARQL" is a textbook architecture predating
OntoBricks by fifteen years.

### 2.2 Free — permissively-licensed OSS doing the heavy lifting

OntoBricks is, to a large extent, **orchestration over open-source libraries**. You may use the exact
same libraries:

| Library | Licence | Does the work of |
|---|---|---|
| `rdflib` | BSD-3 | RDF graph model, Turtle/RDF-XML parsing & serialisation |
| `owlrl` | W3C / BSD | **OWL 2 RL reasoning + deductive closure** |
| `pyshacl` | Apache-2.0 | **SHACL validation** |
| `networkx` | BSD-3 | **Louvain, label propagation, greedy modularity, BFS, shortest path** |
| `strawberry-graphql` | MIT | GraphQL schema + execution |
| `fastapi` / `starlette` / `pydantic` | MIT | Web layer |
| `fastmcp` | Apache-2.0 | MCP server |
| `databricks-sdk`, `databricks-sql-connector` | Apache-2.0 | Databricks connectivity |
| `sigma.js`, `graphology` | MIT | Graph rendering & layout |
| `d3` | ISC | Visualisation |
| `bootstrap`, `chart.js`, `gridjs`, `marked`, `graphiql` | MIT | UI |
| **`D2KLab/Ontology-Pitfalls-Detector`** | **Apache-2.0** | **The ontology pitfalls checks** |

**Critical finding:** the "Ontology Pitfalls Detector with 19 structural, logical and semantic checks"
— marketed as a headline differentiator — is **vendored from an Apache-2.0 academic project**
(`D2KLab/Ontology-Pitfalls-Detector`, itself derived from the published OOPS! pitfall catalogue by
Poveda-Villalón et al.). OntoBricks' own `licenses/README.md` states this. **You can use that upstream
project directly**, under Apache-2.0, with attribution. No clean-room needed for that subsystem at all.

Same applies to community detection: Louvain (Blondel et al., 2008) is a published algorithm shipped
in `networkx`.

### 2.3 Protected — what you must not reproduce

Treat all of the following as off-limits:

- Any **literal source code**, in whole or in fragments
- **File, module, class, and function names** (e.g. their `*Service` / `*Engine` / `*Factory` naming,
  their `src/back/core/...` layout) — reproducing structure is weak evidence of copying and easy to avoid
- Their **LLM prompt texts** — prompts are creative literary expression and are among the most
  copyright-exposed assets in the repo
- Their **registry DDL and triple-table DDL as expressed** (column names, index names, generated-column
  expressions). You will converge on a similar *shape* — that is fine — but write your own DDL
- Their **SQL generation templates** and translation code
- Their **pitfall identifier scheme** (`P1.1`–`P4.7`) and check descriptions — derive your own catalogue
  from the public OOPS! literature or use the Apache-2.0 upstream directly
- **UI code, CSS, SVG icons, fonts, screenshots, diagrams**
- **Documentation prose** — README, architecture docs, user guide
- The names **OntoBricks**, **OntoViz**, **OBX**, and anything evoking Databricks trade dress
  ("...bricks", the `#FF3621` Databricks red)

### 2.4 The residual engineering you genuinely have to build

Strip out Sections 2.1 and 2.2 and what remains as original work is roughly:

1. The **R2RML → SQL compiler** (the real technical core)
2. The **registry / metadata data model** and governance lifecycle
3. **LLM prompt engineering** for ontology generation and auto-mapping
4. The **build/materialisation pipeline** orchestration
5. The **visual ontology editor** UI
6. Warehouse **adapter abstraction** (which they don't have — see Section 5)

That is a real product, but it is application engineering, not research. Estimate in Section 6.

---

## 3. Clean-room methodology

### 3.1 The contamination problem, stated honestly

A reference copy of OntoBricks has been cloned and read during this analysis (in an OS temp
scratchpad — **deliberately never inside the project repository**, so it can never enter git history).
That read informs this document. Standard clean-room practice separates the party that reads the
original from the party that writes the new code. We therefore adopt a **two-track** process.

### 3.2 Two-track process

**Track A — Specification team (may read the reference).**
Produces a functional specification describing *what the system does*, expressed exclusively in terms
of public standards and observable behaviour. The spec may say:

> "The system SHALL compile an R2RML TriplesMap into a SQL SELECT projecting subject, predicate and
> object columns, per W3C R2RML §11."

The spec may **not** contain code, identifiers, prompt text, SQL text, file paths, or prose copied
from the reference.

**Track B — Implementation team (must never access the reference).**
Implements from (a) the Track A specification, (b) the W3C standards documents, and (c) OSS library
documentation. Track B does not clone, read, browse, or receive excerpts from the OntoBricks repo.

### 3.3 Operating rules

| Rule | Detail |
|---|---|
| **R1** | The reference clone lives outside the project tree and is **deleted** once the spec is signed off. It is never committed, never opened in the same editor window as new code. |
| **R2** | `.gitignore` and a pre-commit hook block any path containing the reference. Never `git init` in a directory containing the clone. |
| **R3** | No copy-paste from reference to new code. Ever. Not "as a starting point", not "temporarily". |
| **R4** | Every non-obvious design decision gets an **ADR citing a public source** (W3C spec section, library docs, published paper). This is your provenance trail. |
| **R5** | Deliberately diverge on naming, module layout, and architecture. Divergence is both better engineering (Section 5) and strong evidence of independent creation. |
| **R6** | Do not staff the implementation with anyone who has contributed to `databrickslabs/ontobricks`. |
| **R7** | Keep dated, immutable records: the spec, ADRs, commit history, and a written log of which public sources each subsystem was built from. |
| **R8** | **AI coding assistants used on Track B must not be given the reference repo as context.** Same rule as humans. |
| **R9** | Run a dependency licence scan (`pip-licenses`, `license-checker`) in CI from day one. Flag any GPL/AGPL. Note `psycopg` is **LGPL-3.0** — acceptable when used unmodified as a library, but record the decision. |
| **R10** | Before launch: counsel reviews the licence position, the provenance trail, and the product name for trademark conflict. |

### 3.4 What clean-room does *not* need to protect against

Do not over-engineer this. You are free to:
- Read the **public documentation, website, marketing pages, and screenshots** — these describe
  functionality (unprotected ideas), and competitive analysis of a shipped product is normal and lawful
- Implement the **same features** with the same names users expect ("auto-map", "materialise", "domain")
- Use the **same open-source libraries** and the same W3C standards
- Arrive at a **similar triple-table shape** — a flat `(subject, predicate, object)` table with
  composite indexes is the obvious, near-forced design, dictated by the RDF spec, not by Databricks

---

## 4. Functional capability map (rebuild target)

Derived from public standards and observable product behaviour. This is the Track A spec skeleton;
each item expands into its own specification document.

### C1 — Catalog introspection
Pull table, column, type, comment, and constraint metadata from the target warehouse. Detect primary
and foreign keys. Sample rows for preview. **Behind an adapter interface from commit one.**

### C2 — Ontology model & authoring
- In-memory model: classes, object properties, datatype properties, hierarchy, domain/range, cardinality
- Serialise to / parse from **OWL 2 in Turtle** (`rdflib`)
- Visual canvas editor: drag-and-drop classes, draw relationships and inheritance
- Import industry vocabularies: FIBO (MIT), HL7 FHIR RDF, IOF, CDISC — *verify each vocabulary's own
  licence independently before bundling*
- Import user-supplied OWL/RDFS
- Conflict/consistency detection on merge

### C3 — Ontology quality checks
Use **`D2KLab/Ontology-Pitfalls-Detector` (Apache-2.0) directly**, with attribution. Structural,
logical, and semantic checks on the authored ontology. No reimplementation required.

### C4 — Mapping layer
- Bind each ontology class to a table or SQL query; bind attributes to columns
- Bind relationships to join queries, with forward / reverse / bidirectional direction
- Define subject URI templates (e.g. `{base}/Person/{person_id}`)
- Emit **W3C-compliant R2RML** as the canonical, portable mapping artefact
- Live data preview against real rows
- **Schema-drift detection**: diff stored mapping against current catalog metadata; warn on renamed
  or dropped columns before the build breaks

### C5 — R2RML → SQL compiler *(the technical core)*
Compile the R2RML document into warehouse-native SQL producing a triple stream:
- Each `TriplesMap` → one `SELECT` projecting `subject`, `predicate`, `object` (+ `datatype`, `lang`)
- URI templates → string concatenation with null-guards on template variables
- All TriplesMaps → `UNION ALL` into a single triple-producing view
- Correct RDF term typing: IRIs vs. typed literals vs. language-tagged literals
- **Dialect-aware** emission — this is where the warehouse abstraction earns its keep
- Parameterised identifiers and strict validation — **SQL injection is the top security risk in this
  system**, since user-authored mappings become executable SQL

### C6 — Materialisation / build pipeline
Staged, resumable, cancellable, with progress reporting:
1. Validate ontology + mapping → 2. Compile SQL → 3. Create/replace triple view →
4. Materialise to a physical triple table → 5. Load into the graph store →
6. Build indexes → 7. Record run metrics and lineage

Support full rebuild and incremental update. Persist per-run timings, triple counts, and failures.

### C7 — Triple store backends *(pluggable via a factory)*
- **Lakehouse/Delta** — governed table in the warehouse, zero extra infra (default first target)
- **Postgres** — flat triple table with composite indexes for interactive latency
- **Neo4j** — optional, via the Apache-2.0 Bolt driver
- **None** — ontology-only mode (publish semantics, build no graph)

Common interface: upsert triples, count, BFS traversal, shortest path, transitive closure, neighbour
expansion, full-text entity search.

### C8 — Reasoning
- **OWL 2 RL deductive closure** via `owlrl`
- **SHACL validation** via `pyshacl`, with generated shapes from ontology constraints
- **Rule engine**: Horn-clause rules compiled down to SQL for warehouse-scale execution
- Materialise inferred triples with provenance so they can be distinguished and invalidated

### C9 — Query surfaces
- **SPARQL** endpoint (translate to SQL, or execute in-memory for small graphs)
- **Auto-generated GraphQL schema** from the ontology: each class → a type, each object property →
  a field, each datatype property → a scalar. Resolvers translate to triple-store queries.
- Query cost limits, row caps, and timeouts on every surface

### C10 — Graph exploration UI
Two-phase search (type-ahead → full search), N-hop neighbour expansion, cross-domain bridge
navigation, community detection (`networkx`: Louvain, label propagation, greedy modularity),
explainable cohort discovery (cohort = a saved, human-readable predicate set over graph structure,
with the explanation rendered as the predicates that selected each member).

### C11 — MCP server
Expose the graph to LLM clients. Tool surface (functional requirements — implement your own):
domain listing and selection, ontology description, entity-type inventory, entity description with
BFS traversal, entity context (linked dataset, bridges, actions), computed/virtual attributes,
action invocation, status diagnostics, GraphQL schema + query. Per-domain publication control over
which tools are exposed.

### C12 — Governance
Versioned domains; **DRAFT → IN-REVIEW → PUBLISHED** lifecycle enforced server-side; single-editor
locking with auto-releasing leases and admin takeover; review workflow with configurable quorum;
append-only audit trail; export/import bundle format for promoting domains between environments.

### C13 — LLM automation
- Generate a draft ontology from catalog metadata
- Auto-generate mappings (SQL + column bindings) for every class and relationship
- Conversational ontology assistant (natural-language edits)
- Evaluation harness for mapping-generation quality — **build this early**, it is what makes the LLM
  features trustworthy rather than a demo
- **Model-agnostic provider interface.** Do not hard-wire to Databricks Model Serving.

---

## 5. Architectural divergence — where you should deliberately differ

These are not just legal hygiene; each is a genuine improvement and a competitive differentiator.

| # | OntoBricks | Your design | Why |
|---|---|---|---|
| **D1** | Databricks-coupled throughout (UC, SQL Warehouse, Lakebase, Databricks Apps, UC Volumes) | **Warehouse adapter port from commit one**: `CatalogAdapter`, `SqlDialect`, `ExecutionAdapter`, `StorageAdapter`. Databricks is the first *implementation*, never the assumption. | This is your whole roadmap. Retrofitting it later is the mistake that makes a project unportable. |
| **D2** | Deploys as a Databricks App | **Deployment-neutral container.** Runs on Databricks Apps, but equally on any container host. | Fabric and SQL Server customers will not deploy via Databricks Apps. |
| **D3** | Databricks Model Serving for LLM calls | **Provider-agnostic LLM interface** (Anthropic, OpenAI, Bedrock, Azure OpenAI, Databricks). | Customers have their own model contracts. |
| **D4** | Registry on Lakebase (Postgres) | **Standard Postgres** — Lakebase becomes one deployment option among several. | Removes a hard Databricks dependency from the control plane. |
| **D5** | Server-rendered Jinja + Bootstrap, ~74k LOC JS | Pick deliberately. A typed SPA against a documented API is easier to maintain and to re-skin per customer. | Their UI is the largest chunk of code and the least differentiated. Don't copy the approach by default. |
| **D6** | Prompt engineering embedded in the app | **Versioned prompt assets with an eval harness.** | Prompts are your most valuable and most copyright-sensitive asset. Build them yourself, test them properly. |

**Rule of thumb:** where a design choice is forced by a W3C standard, converge freely. Where it is a
Databricks-specific accommodation, diverge — and you will end up with a better product.

---

## 6. Phased delivery plan

Estimates assume a small senior team (2–4 engineers). Adjust to your staffing.

| Phase | Scope | Exit criterion | Est. |
|---|---|---|---|
| **P0 — Legal & spec** | Counsel review of Section 1 & 3. Delete reference clone. Write Track A spec for C1/C4/C5/C6. Choose name (trademark search). Set up repo, CI, licence scanning, ADR process. | Spec signed off; clean-room rules in force; zero reference material on any dev machine. | 2–3 wks |
| **P1 — Thin vertical slice** | One Databricks table → one ontology class → hand-written mapping → compiled SQL → triple view → row count. No UI, no LLM, no reasoning. Adapter interfaces defined even though only one implementation exists. | `SELECT count(*)` from a generated triple view returns correct triples for a real table. | 4–6 wks |
| **P2 — Mapping & compiler** | Full C4 + C5. R2RML emit/parse. Relationships with direction. URI templates. Schema-drift detection. Hardened SQL injection defences. | Multi-class ontology with relationships materialises correctly; R2RML round-trips; injection test suite passes. | 6–8 wks |
| **P3 — Store & query** | C6 + C7 (Delta + Postgres) + C9 GraphQL. Build pipeline with progress, cancel, resume. | A domain builds end-to-end; GraphQL queries return nested results. | 6–8 wks |
| **P4 — Ontology authoring** | C2 + C3. Visual editor, OWL import/export, pitfalls via the Apache-2.0 upstream. | A user designs an ontology in the UI and builds a graph from it without touching a file. | 8–10 wks |
| **P5 — Explore** | C10. Search, N-hop expansion, communities, cohorts. | Interactive exploration at target latency on a realistic graph. | 6–8 wks |
| **P6 — Reasoning** | C8. OWL 2 RL closure, SHACL validation, rules-to-SQL. | Inferred triples materialise with provenance; SHACL reports render in the UI. | 6–8 wks |
| **P7 — MCP** | C11. | Claude Desktop / Cursor connect and answer questions over a real graph. | 3–4 wks |
| **P8 — LLM automation** | C13 + eval harness. | Auto-generated ontology + mappings reach a measured accuracy bar on a benchmark schema. | 6–8 wks |
| **P9 — Governance** | C12. | Versioning, review workflow, locking, export/import all enforced server-side. | 5–6 wks |
| **P10 — Second warehouse** | Fabric or Snowflake adapter. | Same domain builds on two warehouses from one codebase. | 4–6 wks *(if D1 held)* |

**Sequencing notes**
- P1 → P2 → P3 is the critical path. Everything else can parallelise once the compiler is stable.
- **P10 is the real test of the architecture.** If D1 was honoured, it is a 4–6 week adapter. If not,
  it is a rewrite. Consider building a deliberately thin second adapter during P3 as an early canary.
- Ship the MCP server (P7) earlier than instinct suggests — it is cheap, it is the current buying
  trigger, and it demos extremely well.

---

## 7. Immediate next actions

1. **Counsel review** of Section 1 — confirm the read on field-of-use and at-will termination. *(Blocking for commercial launch, not for P0/P1.)*
2. **Optional, one email:** ask Databricks whether an OEM/relicensing path exists. Do not wait on the answer.
3. **Delete the reference clone** once the Track A spec is written. Confirm nothing sits inside the project tree.
4. **Pick a name** with no "bricks" suffix and no Databricks trade-dress association. Run a trademark search.
5. **Set up the repo**: licence scanning in CI, ADR directory, clean-room rules in `CONTRIBUTING.md`.
6. **Write the P1 spec** and start the thin vertical slice.

## 8. Open decisions for you

- **Scope of first release** — Databricks-only GA, or hold GA until a second warehouse proves the adapter?
- **Clean-room strictness** — full two-track separation (slower, strongest position), or single-track
  with disciplined rules R1–R9 (faster, weaker if challenged)? Depends on your risk appetite and
  whether you intend to sell into enterprises that will diligence provenance.
- **UI strategy** — rebuild a comparable visual editor, or start API/MCP-first and add the canvas later?
- **Build vs. buy on the graph store** — flat triple table everywhere, or lean on a real graph DB sooner?
