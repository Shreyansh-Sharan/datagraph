from __future__ import annotations

import psycopg

from .base import Connector, ConnectorSpec, Field, TestResult


class PostgresConnector(Connector):
    spec = ConnectorSpec(
        kind="postgres", label="PostgreSQL", category="source", secret_field="password",
        fields=(
            Field("host", "Host"), Field("port", "Port", kind="number", default=5432), Field("database", "Database"),
            Field("user", "User"), Field("password", "Password", kind="password", required=False),
            Field("schema", "Default schema", required=False, default="public", help="Schema the catalog browser opens on"),
            Field("sslmode", "SSL mode", kind="select", required=False, default="prefer", options=("disable", "prefer", "require")),
        ),
        docs="https://www.postgresql.org/docs/current/libpq-connect.html",
    )

    @staticmethod
    def url(config: dict, secret: str | None) -> str:
        pw = f":{secret}" if secret else ""
        return f"postgresql://{config['user']}{pw}@{config['host']}:{config.get('port', 5432)}/{config['database']}?sslmode={config.get('sslmode', 'prefer')}"

    def _probe(self, config: dict, secret: str | None) -> TestResult:
        with psycopg.connect(self.url(config, secret), connect_timeout=5) as conn:
            version = conn.execute("SELECT version()").fetchone()[0]
            schema = config.get("schema") or "public"
            tables = conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = %s", (schema,)).fetchone()[0]
        short = version.split(" on ")[0]
        return TestResult(True, "Connected", f"{short} · {tables} tables in {schema}", facts={"version": short, "tables": tables, "schema": schema})

    def advice(self, message: str) -> str | None:
        if "password authentication failed" in message:
            return "Check the user and password; on managed Postgres the user may need the server suffix (user@server)."
        if "does not exist" in message:
            return "The database or role does not exist on this server."
        if "Connection refused" in message or "timeout" in message.lower():
            return "The host or port is unreachable from this deployment; check firewall rules and the port."
        return None
