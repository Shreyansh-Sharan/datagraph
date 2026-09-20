"""String templates (R2RML §7.3), SQL identifier safety, and dialect primitives."""
import pytest

from ontoforge.compiler.template import parse_template, ColumnRef
from ontoforge.compiler.identifiers import validate_column, validate_table, IdentifierError
from ontoforge.dialects import DatabricksDialect, SQLiteDialect


# -- templates ---------------------------------------------------------------

def test_template_splits_literal_text_and_column_references():
    assert parse_template("http://data.example.com/emp/{EMPNO}/dept/{DEPTNO}") == (
        "http://data.example.com/emp/", ColumnRef("EMPNO"), "/dept/", ColumnRef("DEPTNO"))


def test_template_escaped_braces_are_literal_text():  # §7.3: "\{" and "\}" escape
    assert parse_template(r"http://x/\{lit\}/{A}") == ("http://x/{lit}/", ColumnRef("A"))


def test_template_delimited_column_name():  # column names in templates follow SQL identifier rules
    assert parse_template('{"First Name"}') == (ColumnRef("First Name"),)


def test_template_unbalanced_brace_is_an_error():
    with pytest.raises(ValueError):
        parse_template("http://x/{A")


# -- identifiers --------------------------------------------------------------

@pytest.mark.parametrize("name", ["EMP", "main.default.emp", "_t1", '"Odd Name"'])
def test_valid_table_names_accepted(name):
    validate_table(name)


@pytest.mark.parametrize("name", ["EMP; DROP TABLE x", "a.b.c.d", "", "emp--", "e m p", "x`y"])
def test_dangerous_table_names_rejected(name):
    with pytest.raises(IdentifierError):
        validate_table(name)


def test_column_name_rejects_injection():
    with pytest.raises(IdentifierError):
        validate_column("a) FROM t; --")


def test_delimited_column_name_is_unwrapped():
    assert validate_column('"First Name"') == "First Name"
    assert validate_column("ENAME") == "ENAME"


# -- dialects ------------------------------------------------------------------

def test_databricks_quotes_with_backticks_and_dots():
    d = DatabricksDialect()
    assert d.quote_identifier("First Name") == "`First Name`"
    assert d.quote_table("main.default.emp") == "`main`.`default`.`emp`"
    assert d.quote_identifier("we`ird") == "`we``ird`"


def test_databricks_string_literal_escapes_quotes_and_backslashes():
    d = DatabricksDialect()
    assert d.string_literal("O'Brien\\x") == "'O\\'Brien\\\\x'"


def test_databricks_concat_and_text_cast():
    d = DatabricksDialect()
    assert d.concat(["'a'", "`B`"]) == "concat('a', `B`)"
    assert d.to_text("`B`") == "CAST(`B` AS STRING)"


def test_sqlite_dialect_primitives():
    d = SQLiteDialect()
    assert d.quote_identifier('a"b') == '"a""b"'
    assert d.string_literal("it's") == "'it''s'"
    assert d.concat(["'a'", '"B"']) == "('a' || \"B\")"
    assert d.to_text('"B"') == 'CAST("B" AS TEXT)'
