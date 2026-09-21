from __future__ import annotations

from .base import Connector, ConnectorSpec, Field, TestResult


class SqlServerConnector(Connector):
    """SQL Server / Azure SQL / Fabric warehouse over ``pyodbc`` (preferred) or ``pymssql``."""

    spec = ConnectorSpec(
        kind="sqlserver", label="SQL Server", category="source", secret_field="password",
        fields=(
            Field("host", "Host"), Field("port", "Port", kind="number", default=1433), Field("database", "Database"),
            Field("user", "User"), Field("password", "Password", kind="password", required=False),
            Field("schema", "Default schema", required=False, default="dbo"),
            Field("driver", "Driver", kind="select", required=False, default="auto", options=("auto", "pyodbc", "pymssql")),
            Field("encrypt", "Encrypt", kind="select", required=False, default="yes", options=("yes", "no")),
        ),
        docs="https://learn.microsoft.com/sql/connect/python/python-driver-for-sql-server",
    )

    def _probe(self, config: dict, secret: str | None) -> TestResult:
        driver = config.get("driver", "auto")
        pyodbc = pymssql = None
        if driver in ("auto", "pyodbc"):
            try:
                import pyodbc  # type: ignore
            except ImportError:
                pyodbc = None
        if driver in ("auto", "pymssql") and pyodbc is None:
            try:
                import pymssql  # type: ignore
            except ImportError:
                pymssql = None
        if pyodbc is None and pymssql is None:
            return TestResult(False, "Driver not installed", "Neither pyodbc nor pymssql is installed in this deployment.",
                              action="Install a driver: pip install pyodbc (needs the Microsoft ODBC Driver 18) or pip install pymssql.")
        host, port, db, user = config["host"], config.get("port", 1433), config["database"], config["user"]
        if pyodbc is not None:
            dsn = (f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={host},{port};DATABASE={db};UID={user};PWD={secret or ''};"
                   f"Encrypt={config.get('encrypt', 'yes')};TrustServerCertificate=no;Connection Timeout=5")
            conn = pyodbc.connect(dsn)
        else:
            conn = pymssql.connect(server=host, port=port, database=db, user=user, password=secret or "", login_timeout=5)
        try:
            cur = conn.cursor()
            cur.execute("SELECT @@VERSION")
            version = str(cur.fetchone()[0]).splitlines()[0]
            cur.execute("SELECT count(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = %s" if pymssql is not None and pyodbc is None else
                        "SELECT count(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = ?", (config.get("schema", "dbo"),))
            tables = cur.fetchone()[0]
        finally:
            conn.close()
        return TestResult(True, "Connected", f"{version} · {tables} tables in {config.get('schema', 'dbo')}", facts={"version": version, "tables": tables})

    def advice(self, message: str) -> str | None:
        if "Login failed" in message:
            return "Check the user and password; Azure SQL users may need the form user@server."
        if "ODBC Driver" in message and "not found" in message.lower():
            return "Install the Microsoft ODBC Driver 18 for SQL Server or switch the driver to pymssql."
        if "timed out" in message.lower() or "Unable to connect" in message:
            return "The host or port is unreachable from this deployment; check the server firewall."
        return None
