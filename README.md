# ontoforge

A semantic-layer / knowledge-graph backend: design an ontology, map it onto warehouse tables with
W3C R2RML, materialise the graph as SQL inside the warehouse, reason over it, and expose it through
REST, GraphQL and MCP. Postgres is the registry and the default graph store; Databricks is the
first warehouse target, with the dialect/catalog/source ports built for Fabric, Snowflake and
SQL Server to follow.

## Where things live

Four folders, one job each. Each side of the product keeps its own tests, because that is where
pytest and vitest look for them.

```
backend/    the Python package and its suite: API, MCP server, compiler, build pipeline, registry
frontend/   the React app and its suite (pnpm; it is the only interface)
deploy/     images, compose, pipelines, and the scripts for a developer machine
docs/       architecture decisions, the gap analysis, design notes
```

## Run it

One command starts Postgres in Docker, seeds a demo schema, serves the API and opens the browser:

```bash
make start                 # http://127.0.0.1:8765/ui/  — Ctrl-C to stop
make install-service       # macOS: start at login and keep running (make uninstall-service to remove)
```

Step by step:

```bash
make db                                    # Postgres 16 on :5439
uv venv && uv pip install -e "./backend[dev]"
pytest                                     # 380 behaviour tests against the live Postgres
.venv/bin/python -m ontoforge migrate      # apply migrations
.venv/bin/python -m ontoforge serve        # REST API on http://127.0.0.1:8000 (docs at /docs)
.venv/bin/python -m ontoforge serve-mcp    # MCP server over stdio (Claude Desktop, Cursor, ...)
.venv/bin/python -m ontoforge compile m.ttl --dialect databricks --view main.kg.triples
```

The React app runs against that API:

```bash
cd frontend && pnpm install && pnpm run dev   # http://127.0.0.1:5173, proxying to :8765
pnpm run typecheck && pnpm exec vitest run    # or `make test-ui` from the root
```

Configuration is environment-driven; see `.env.example` for a developer machine and
`deploy/.env.example` for a deployment.

## The pipeline

```
catalog metadata ──autodraft / LLM──▶ Ontology (OWL 2) ──▶ MappingSpec ──▶ R2RML ──compiler──▶ SQL
                                                                                          │
   MCP · GraphQL · REST ◀── TripleStore (Postgres) ◀── build pipeline ◀───────────────────┘
                              │
                      OWL 2 RL closure · SHACL validation
```

| Package | Role | Public standard / source |
|---|---|---|
| `r2rml/` | Mapping document model, Turtle parser/serialiser | W3C R2RML §5–§8 |
| `compiler/` | R2RML → one `UNION ALL` triple-producing SQL statement; strict identifier validation | R2RML §7.3, §10, §11; OWASP |
| `dialects/` | `SqlDialect` port: Databricks (Spark SQL), Postgres, SQLite | ADR 0002 |
| `catalog/` | `CatalogAdapter` port: column types, PK/FK — Databricks (`information_schema`), Postgres | ADR 0002 |
| `ontology/` | Classes/properties model, OWL 2 Turtle round-trip, structural checks | OWL 2 / RDFS |
| `mapping/` | `MappingSpec` (class→table, attributes, join-free relations) → R2RML | — |
| `autodraft.py` | Ontology + mapping from PK/FK metadata, no LLM | — |
| `llm/` | `LLMProvider` port (Anthropic first); draft ontology, suggest mapping, NL edits; output validated | ADR 0004 |
| `registry/` | Domains, versions, DRAFT→IN_REVIEW→PUBLISHED, editor lease, reviews with quorum, build runs, audit log | — |
| `store/` | Triple store on Postgres: COPY / INSERT-SELECT loads, search, describe, N-hop neighbourhood, inventories, inferred layer | — |
| `build/` | `SourceEngine` port (Postgres, Databricks); pipeline with live step progress, drift check, optional publish of the triple view/table into the warehouse; background scheduler with cancellation | — |
| `reasoning/` | OWL 2 RL closure (`owlrl`), SHACL validation (`pyshacl`) with shapes generated from the ontology | W3C OWL 2 RL, SHACL |
| `graphql/` | GraphQL schema generated from the ontology, resolved against the store (`graphql-core`) | GraphQL spec |
| `metadata.py` | Per-version snapshots of source tables (columns, keys, comments), refresh diffs, schema-drift detection | — |
| `rules/` | SWRL rules: presentation-syntax parser, SQL compilation over the triple table, fixpoint materialisation, violation mode | W3C SWRL submission |
| `quality/` | Data-quality constraints (14 kinds, 3 severities), SHACL import/export, constraints derived from the ontology, SQL validation | W3C SHACL |
| `analytics.py` | Communities (Louvain / label propagation / greedy modularity), centralities, health flags, AI interpretation, recorded runs | networkx |
| `attachments.py` | Datasets, class actions, virtual attributes (live SQL bound to entity keys), cross-domain bridges | — |
| `cohorts.py` | Explainable entity groups from criteria; materialisable as triples | — |
| `bundle.py` | Multi-version domain export/import with conflict modes | — |
| `auth/` | Header or API-key authentication; roles viewer < builder < reviewer < admin | — |
| `observability.py` | JSON/text logging, request ids, request timing, build events | — |
| `api/` | FastAPI REST surface for all of the above | — |
| `mcp/` | MCP server: the whole backend as tools. Read the graph (`describe_ontology`, `search_entities`, `describe_entity`, `class_schema`, `ontology_paths`, `graph_aggregate`, `query_graphql`); design the draft (`add_class`, `map_class`, `add_attribute`, `add_relationship`, `map_relationship`, `remove_relationship`, `exclude_property`, `unmap_class`); snapshot tables (`import_tables`, `refresh_metadata`); profile and check quality (`run_profile`, `table_quality`, `add_quality_rule`, `failing_rows`); glossary (`add_term`, `update_term`, `delete_term`); reasoning rules and constraints (`add_rule`, `add_constraint`); build (`start_build`, incremental); lifecycle (`create_version`, `transition_version`, `review_version`, `set_active_version`); domain settings and MCP policy. Every action runs as the caller under the lease, role and policy. | MCP spec |

## Triple table

One shared table, keyed by domain version:

| column | meaning |
|---|---|
| `subject` / `predicate` / `object` | IRIs, `_:`-prefixed blank nodes, or literal lexical forms |
| `object_type` | `iri` / `bnode` / `literal` |
| `datatype`, `lang` | typed / language-tagged literals |
| `inferred` | written by the reasoner; cleared on rebuild |

## REST API (summary)

`/domains`, `/domains/{name}/versions`, `/versions/{id}` (+ `/ontology`, `/ontology/checks`,
`/mapping`, `/mapping/r2rml`, `/mapping/sql?dialect=`), lifecycle (`/transition`, `/reviews`,
`/lease`, `/audit`), `/builds`, graph (`/graph/status`, `/graph/search`, `/graph/entity`,
`/graph/neighbourhood`), reasoning (`/reasoning/infer`, `/reasoning/validate`, `/reasoning/shapes`),
`/graphql` (+ `/graphql/schema`), `/catalog/tables`, `/autodraft`, `/llm/draft-ontology`,
`/llm/suggest-mapping`, `/llm/assist`. Interactive docs at `/docs` when serving.

## Sources: Databricks and Postgres alike

A domain reads one or more connections of the connection module (`mf-studio-connectors`), of kind
`databricks` or `postgres`; the deployment's own source (`ONTOFORGE_SOURCE_KIND`) is the fallback.
Everything downstream is written once against the two ports: the catalog (`catalog/`: schemas,
tables, columns, keys) and the SQL dialect (`dialects/`: quoting, `count_if`, `regex_match`,
`hours_ago`, `days_before`, quantiles, distinct counts). Snapshots, drafting, mapping, builds
(incremental, with per-table signatures), profiles, data-quality rules of every kind, the glossary,
the graph tools and the assistant therefore run unchanged on a Postgres schema. The `retail`
domain in the demo is a Postgres schema of 20,000 orders read through a hub connection; the
`adventureworks` domain is Databricks. Table names are spelled as the source spells them,
`schema.table` on Postgres and `catalog.schema.table` on Databricks, in snapshots, mappings and
rules alike; a draft qualifies the names it finds so the two always meet. After each load the
build refreshes the planner's statistics on the triple table, without which every graph query on
a freshly loaded version crawls.

## Operations

- **Auth** — `ONTOFORGE_AUTH_MODE=header` trusts an identity header (default `X-Actor`; on Databricks
  Apps use `X-Forwarded-Email`); `token` requires `Authorization: Bearer <key>` from `/admin/api-keys`.
  Unknown principals get `ONTOFORGE_AUTH_DEFAULT_ROLE` (`viewer`). Roles: viewer < builder < reviewer < admin.
- **Builds** run in the background: `POST /versions/{id}/builds` → 202, poll `GET /builds/{id}`,
  `POST /builds/{id}/cancel`; `?wait=true` blocks. Steps (`compile`, `drift`, `prepare`, `publish`,
  `load`, `finalize`) are recorded live.
- **Publish into the warehouse** — `ONTOFORGE_WAREHOUSE_TARGET_SCHEMA=main.kg` +
  `ONTOFORGE_WAREHOUSE_MATERIALIZATION=view|table` creates `<schema>.<domain>_v<n>_triples`
  (and a `_mat` snapshot table) in the source warehouse before loading the store from it.
- **Metadata** — `POST /versions/{id}/metadata/import` snapshots source tables; `/refresh` diffs the
  catalog; `GET /versions/{id}/mapping/drift` lists dropped/renamed/retyped columns the mapping relies on.
- **Logs** — `ONTOFORGE_LOG_FORMAT=json` for one JSON object per line; every response carries `X-Request-ID`.

## UI

`frontend/` is the product's interface: a React app served by its own nginx image. Domains and
versions with the review lifecycle, metadata snapshots and profiles, the ontology map, the mapping
designer, data-quality rules, builds with live progress, graph exploration and the assistant, with
every activity arriving in the bell.

A dependency-free single-page app also ships inside the package and is what the API serves at
`/ui/`. It covers the same workflow with no build step and is kept for deployments that run the
API alone; new work goes into `frontend/`.

## Deploy

Two images, one database, a pipeline each: see [deploy/README.md](deploy/README.md).

```bash
cp deploy/.env.example deploy/.env
docker compose -f deploy/compose.yml up -d --build   # http://localhost:8080
```

## Not yet

Named graphs (`rr:graphMap`), `rr:inverseExpression`, relative-IRI templates; OWL union/intersection
class expressions; conditional (IF-guarded) SHACL rules; `.swrl` RDF import; Neo4j as a graph
store; the D2KLab pitfall scanner (Apache-2.0, heavy ML dependencies); a UI.
See [docs/GAP-ANALYSIS.md](docs/GAP-ANALYSIS.md).

## Provenance

Built from public standards and library documentation under the clean-room rules in
[docs/REBUILD-PLAN.md](docs/REBUILD-PLAN.md) §3. Design decisions are recorded in `docs/adr/`.
