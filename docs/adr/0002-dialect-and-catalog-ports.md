# ADR 0002 — Warehouse access goes through two ports: SqlDialect and CatalogAdapter

**Status:** accepted · **Date:** 2026-09-20

## Decision
The compiler never references a concrete warehouse. It speaks to `SqlDialect` (how to spell
identifiers, literals, concatenation, casts, percent-encoding, typed NULL) and to
`CatalogAdapter` (column SQL types for R2RML §10.2 natural datatype mapping). Databricks is the
first implementation of each; SQLite is the second and doubles as the in-process test target.

## Sources
- R2RML §7.3 (IRI-safe template values), §10.2 (natural mapping of SQL values), §11 (generated RDF)
- Spark SQL function reference: `concat`, `url_encode`, `CAST` — https://docs.databricks.com/sql/language-manual/
- Unity Catalog `system.information_schema.columns` — https://docs.databricks.com/sql/language-manual/information-schema/columns.html
- Ports-and-adapters (Cockburn, 2005)

## Why
Multi-warehouse support (Fabric, Snowflake, SQL Server) is the roadmap. Retrofitting a dialect
layer after the fact is the failure mode that makes such projects unportable; putting the port
in at commit one costs almost nothing.

## Consequences
- Adding a warehouse = one dialect class (~30 lines) + one catalog class (~30 lines).
- The Databricks `url_encode` form-encodes spaces as `+`; the dialect rewrites to `%20`. Characters
  `*`/`~` differ marginally from the R2RML iunreserved set; documented deviation.
- `null_text()` exists because `UNION ALL` branches must agree on column types for CTAS.
