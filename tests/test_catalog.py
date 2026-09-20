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
