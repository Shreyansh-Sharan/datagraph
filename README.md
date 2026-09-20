# ontoforge

Compiles W3C **R2RML** mappings into warehouse-native SQL that materialises a knowledge graph
(a triple stream) directly inside the warehouse. First target: Databricks. The compiler is
dialect-agnostic; adding a warehouse means adding one `SqlDialect` and one `CatalogAdapter`.

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/python -m ontoforge compile mapping.ttl --dialect databricks --view main.kg.triples
```

## What the compiler produces

One SQL statement, `UNION ALL` of one `SELECT` per generated triple pattern, with columns

| column | meaning |
|---|---|
| `subject` | IRI, or `_:`-prefixed blank node id |
| `predicate` | IRI |
| `object` | IRI, `_:`-prefixed blank node id, or literal lexical form |
| `object_type` | `iri` / `bnode` / `literal` |
| `datatype` | datatype IRI for typed literals, else NULL |
| `lang` | language tag, else NULL |

Semantics are taken from the R2RML Recommendation (§11 "Generated RDF"): rows with a NULL in
any column used by a term produce no triple; IRI templates percent-encode column values;
referencing object maps become joins; `rr:class` yields `rdf:type` triples; column-valued
literals without an explicit `rr:datatype` take the natural XSD type of the column (§10.2)
when a `CatalogAdapter` is supplied.

## Layout

```
src/ontoforge/
  r2rml/      model, Turtle parser, Turtle serialiser        (spec: R2RML §5–§8)
  compiler/   templates, identifier validation, SQL compiler (spec: R2RML §7.3, §10, §11)
  dialects/   SqlDialect port — Databricks (Spark SQL), SQLite (tests / ANSI reference)
  catalog/    CatalogAdapter port — Databricks Unity Catalog via information_schema
  cli.py      python -m ontoforge compile
tests/        behaviour tests; compiler tests execute generated SQL on SQLite
docs/adr/     architecture decision records, each citing its public source
```

## Not yet supported (R2RML)

`rr:graphMap` / named graphs (ignored), `rr:inverseExpression` (ignored), relative IRI
resolution against a base (templates must be absolute), `rr:sqlVersion` (ignored).

## Provenance

Built from the public W3C R2RML Recommendation and library documentation under the
clean-room rules in [docs/REBUILD-PLAN.md](docs/REBUILD-PLAN.md) §3. Each design decision
is recorded in `docs/adr/` with its public source.
