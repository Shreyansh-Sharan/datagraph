"""Catalog port: supplies column SQL types so the compiler can apply R2RML §10.2 natural datatypes."""
import pytest

from ontoforge.catalog import DatabricksCatalog
from ontoforge.compiler.identifiers import IdentifierError
from ontoforge.r2rml import LogicalTable


class FakeRunner:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def __call__(self, sql, params):
        self.calls.append((sql, params))
        return self.rows


def test_column_types_queries_information_schema_with_bound_parameters():
    runner = FakeRunner([("EMPNO", "int"), ("ENAME", "string")])
    cat = DatabricksCatalog(runner)
    assert cat.column_types("main.hr.emp") == {"EMPNO": "int", "ENAME": "string"}
    (sql, params), = runner.calls
    assert "information_schema.columns" in sql and "?" in sql and "'" not in sql.replace("''", "")
    assert params == ("main", "hr", "emp")


def test_short_table_names_use_default_catalog_and_schema():
    runner = FakeRunner([])
    DatabricksCatalog(runner, default_catalog="main", default_schema="hr").column_types("emp")
    assert runner.calls[0][1] == ("main", "hr", "emp")


def test_resolver_is_case_insensitive_and_cached():
    runner = FakeRunner([("EMPNO", "bigint")])
    resolve = DatabricksCatalog(runner).resolver()
    lt = LogicalTable(table_name="main.hr.emp")
    assert resolve(lt, "empno") == "bigint"
    assert resolve(lt, "EMPNO") == "bigint"
    assert resolve(lt, "missing") is None
    assert len(runner.calls) == 1


def test_resolver_returns_none_for_sql_query_tables():
    runner = FakeRunner([("X", "int")])
    resolve = DatabricksCatalog(runner).resolver()
    assert resolve(LogicalTable(sql_query="SELECT 1 AS X"), "X") is None
    assert runner.calls == []


def test_malicious_table_name_never_reaches_the_warehouse():
    runner = FakeRunner([])
    with pytest.raises(IdentifierError):
        DatabricksCatalog(runner).column_types("emp' OR 1=1 --")
    assert runner.calls == []


def test_every_migration_table_is_excluded_from_catalog_listing(db):
    """Guard: a new migration table must be added to INTERNAL_TABLES or it would be offered as a mapping source."""
    from ontoforge.catalog import PostgresCatalog
    from ontoforge.catalog.postgres import INTERNAL_TABLES
    with db.transaction() as cur:
        created = {r[0] for r in cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'")}
    assert created <= INTERNAL_TABLES, created - INTERNAL_TABLES
    assert PostgresCatalog(db).list_tables() == []


class KeyRunner:
    """Answers the constraint queries the way Unity Catalog does."""

    def __init__(self, rows_by_sql):
        self.rows_by_sql, self.calls = rows_by_sql, []

    def __call__(self, sql, params):
        self.calls.append((sql, params))
        for marker, rows in self.rows_by_sql.items():
            if marker in sql:
                return rows
        return []


def test_databricks_reports_the_primary_key_unity_catalog_declares():
    runner = KeyRunner({"PRIMARY KEY": [("empno",), ("hired",)]})
    cat = DatabricksCatalog(runner, default_catalog="main", default_schema="hr")
    assert cat.primary_key("emp") == ("empno", "hired")
    sql, params = runner.calls[0]
    assert "key_column_usage" in sql and "table_constraints" in sql and params == ("main", "hr", "emp")
    assert "emp" not in sql.replace("key_column_usage", "")   # the table is bound, never interpolated


def test_databricks_reports_foreign_keys_with_their_referenced_table():
    runner = KeyRunner({"FOREIGN KEY": [("fk_dept", "deptno", "main", "hr", "dept", "deptno"),
                                        ("fk_mgr", "manager", "main", "hr", "emp", "empno")]})
    cat = DatabricksCatalog(runner, default_catalog="main", default_schema="hr")
    assert cat.foreign_keys("emp") == [(("deptno",), "main.hr.dept", ("deptno",)),
                                       (("manager",), "main.hr.emp", ("empno",))]


def test_a_composite_foreign_key_keeps_its_column_order():
    runner = KeyRunner({"FOREIGN KEY": [("fk", "a", "main", "hr", "t", "x"), ("fk", "b", "main", "hr", "t", "y")]})
    cat = DatabricksCatalog(runner, default_catalog="main", default_schema="hr")
    assert cat.foreign_keys("emp") == [(("a", "b"), "main.hr.t", ("x", "y"))]
