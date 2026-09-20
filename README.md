# ontoforge

A semantic-layer / knowledge-graph backend: design an ontology, map it onto warehouse tables with
W3C R2RML, materialise the graph as SQL inside the warehouse, reason over it, and expose it through
REST, GraphQL and MCP. Postgres is the registry and the default graph store; Databricks is the
first warehouse target, with the dialect/catalog/source ports built for Fabric, Snowflake and
SQL Server to follow.

## Run it

```bash
docker compose up -d                       # Postgres 16 on :5439
uv venv && uv pip install -e ".[dev]"
.venv/bin/pytest                           # 150+ behaviour tests against the live Postgres
.venv/bin/python -m ontoforge migrate      # apply migrations
.venv/bin/python -m ontoforge serve        # REST API on http://127.0.0.1:8000 (docs at /docs)
.venv/bin/python -m ontoforge serve-mcp    # MCP server over stdio (Claude Desktop, Cursor, ...)
.venv/bin/python -m ontoforge compile m.ttl --dialect databricks --view main.kg.triples
```

Configuration is environment-driven; see `.env.example`.

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
| `build/` | `SourceEngine` port (Postgres, Databricks) + build pipeline with per-step timings and rollback on failure | — |
| `reasoning/` | OWL 2 RL closure (`owlrl`), SHACL validation (`pyshacl`) with shapes generated from the ontology | W3C OWL 2 RL, SHACL |
| `graphql/` | GraphQL schema generated from the ontology, resolved against the store (`graphql-core`) | GraphQL spec |
| `api/` | FastAPI REST surface for all of the above | — |
| `mcp/` | MCP server: `list_domains`, `describe_ontology`, `graph_status`, `search_entities`, `describe_entity`, `get_graphql_schema`, `query_graphql` | MCP spec |

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

## Not yet

Named graphs (`rr:graphMap`), `rr:inverseExpression`, relative-IRI templates; asynchronous builds
(builds run inside the request today); community detection / cohorts; a UI.

## Provenance

Built from public standards and library documentation under the clean-room rules in
[docs/REBUILD-PLAN.md](docs/REBUILD-PLAN.md) §3. Design decisions are recorded in `docs/adr/`.
