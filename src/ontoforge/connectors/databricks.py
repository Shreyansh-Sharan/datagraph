from __future__ import annotations

from .base import Connector, ConnectorSpec, Field, TestResult


class DatabricksConnector(Connector):
    spec = ConnectorSpec(
        kind="databricks", label="Databricks SQL warehouse", category="source", secret_field="token",
        fields=(
            Field("host", "Workspace host", help="adb-<id>.<n>.azuredatabricks.net, without https://"),
            Field("http_path", "HTTP path", help="/sql/1.0/warehouses/<warehouse id>"),
            Field("token", "Access token", kind="password", required=False),
            Field("catalog", "Catalog", required=False, help="Unity Catalog name used as the session default"),
            Field("schema", "Default schema", required=False),
        ),
        docs="https://docs.databricks.com/dev-tools/python-sql-connector.html",
    )

    def _probe(self, config: dict, secret: str | None) -> TestResult:
        from ontoforge.build import databricks_connect_factory
        host = config["host"].replace("https://", "").rstrip("/")
        connect = databricks_connect_factory(host, config["http_path"], secret or "", config.get("catalog"), config.get("schema"))
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT current_catalog(), current_schema(), current_user()")
            catalog, schema, user = cur.fetchone()
            tables = None
            if config.get("catalog"):
                cur.execute(f"SELECT count(*) FROM {config['catalog']}.information_schema.tables" + (" WHERE table_schema = ?" if config.get("schema") else ""),
                            [config["schema"]] if config.get("schema") else [])
                tables = cur.fetchone()[0]
        detail = f"{user} on {catalog}.{schema}" + (f" · {tables} tables" if tables is not None else "")
        return TestResult(True, "Connected", detail, facts={"catalog": catalog, "schema": schema, "user": user, "tables": tables})

    def advice(self, message: str) -> str | None:
        if "INSUFFICIENT_PERMISSIONS" in message or "PERMISSION_DENIED" in message:
            return "Ask the workspace admin for USE CATALOG / USE SCHEMA / SELECT on the catalog for this principal."
        if "Invalid access token" in message or "403" in message or "401" in message:
            return "The access token is invalid or expired; create a new personal access token or service-principal token."
        if "does not exist" in message or "not found" in message.lower():
            return "Check the HTTP path: it must point at a running SQL warehouse."
        return None
