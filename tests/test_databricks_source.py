"""Databricks source engine, driven through a fake DB-API connection (no workspace needed)."""
from ontoforge.build import DatabricksSource
from ontoforge.dialects import DatabricksDialect


class FakeCursor:
    def __init__(self, rows):
        self.rows, self.executed, self.closed = rows, [], False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return self

    def fetchmany(self, n):
        out, self.rows = self.rows[:n], self.rows[n:]
        return out

    def fetchall(self):
        out, self.rows = self.rows, []
        return out

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class FakeConnection:
    def __init__(self, rows):
        self.cursors, self.rows = [], rows

    def cursor(self):
        c = FakeCursor(list(self.rows))
        self.cursors.append(c)
        return c

    def close(self):
        pass


def test_stream_yields_rows_in_batches():
    conn = FakeConnection([("s1", "p", "o", "iri", None, None), ("s2", "p", "o", "iri", None, None), ("s3", "p", "o", "iri", None, None)])
    src = DatabricksSource(lambda: conn, default_catalog="main", default_schema="hr")
    rows = list(src.stream("SELECT 1", batch=2))
    assert [r[0] for r in rows] == ["s1", "s2", "s3"]
    assert conn.cursors[0].executed[0][0] == "SELECT 1" and conn.cursors[0].closed


def test_dialect_and_catalog_are_databricks_flavoured():
    conn = FakeConnection([("EMPNO", "int"), ("ENAME", "string")])
    src = DatabricksSource(lambda: conn, default_catalog="main", default_schema="hr")
    assert isinstance(src.dialect, DatabricksDialect)
    assert src.catalog.column_types("emp") == {"EMPNO": "int", "ENAME": "string"}
    (sql, params), = conn.cursors[0].executed
    assert params == ("main", "hr", "emp")


def test_prepare_is_a_no_op_for_databricks():
    src = DatabricksSource(lambda: FakeConnection([]), default_catalog="main", default_schema="hr")
    src.prepare()


def test_connect_factory_sets_session_catalog_and_schema(monkeypatch):
    import databricks.sql as dbsql
    from ontoforge.build import databricks_connect_factory
    calls = []
    monkeypatch.setattr(dbsql, "connect", lambda **kw: calls.append(kw) or "conn")
    connect = databricks_connect_factory("h", "/p", "t", catalog="finops_metadata", schema="gold")
    assert connect() == "conn"
    assert calls[-1] == {"server_hostname": "h", "http_path": "/p", "access_token": "t", "catalog": "finops_metadata", "schema": "gold"}
    databricks_connect_factory("h", "/p", "t")()
    assert "catalog" not in calls[-1] and "schema" not in calls[-1]
