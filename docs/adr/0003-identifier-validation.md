# ADR 0003 — Every identifier in a mapping is validated before it becomes SQL

**Status:** accepted · **Date:** 2026-09-20

## Decision
Table and column names from mapping documents must match a conservative grammar (bare
`[A-Za-z_][A-Za-z0-9_]*`, up to three dotted parts, or a `"delimited"` name with no control
characters) before any dialect quotes them. `rr:sqlQuery` text is wrapped as a subquery and
rejected if it contains `;`. Catalog lookups bind table parts as query parameters, never by
string formatting.

## Sources
- OWASP SQL Injection Prevention Cheat Sheet — https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html
- R2RML §5.1 (table names are SQL identifiers), §7.3 (column names in templates follow SQL identifier rules)

## Why
Mapping documents are user-authored and become executable SQL in the customer's warehouse.
This is the highest-impact attack surface in the system.

## Consequences
- `IdentifierError` at compile time rather than a warehouse error (or worse) at run time.
- `rr:sqlQuery` remains trusted input by nature; it is constrained, not sanitised. Document this
  for the authoring layer: queries must be reviewed like any other SQL.
