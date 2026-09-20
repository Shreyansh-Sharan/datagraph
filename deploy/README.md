# Deploying ontoforge

## Container (any host)
```bash
docker build -t ontoforge .
docker run -p 8000:8000 -e ONTOFORGE_DATABASE_URL=postgresql://user:pw@host:5432/db ontoforge
```
Migrations run at startup. Health: `GET /health`. OpenAPI: `/docs`. MCP (Streamable HTTP): `/mcp`.

## Databricks Apps
`deploy/app.yaml` is the app manifest. Provide the referenced secrets/resources (Postgres/Lakebase URL,
SQL Warehouse HTTP path, token). The Apps proxy forwards the signed-in user as `X-Forwarded-Email`,
which is the identity header configured there; assign roles with `PUT /admin/principals/{email}` as
an admin (bootstrap the first admin with `ONTOFORGE_AUTH_DEFAULT_ROLE=admin` once, then set it back).

## Other warehouses
Set `ONTOFORGE_SOURCE_KIND=postgres` to map tables that live in the registry database, or add a
`SourceEngine` + `SqlDialect` + `CatalogAdapter` for a new warehouse (see ADR 0002).
