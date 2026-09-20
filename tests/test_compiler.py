"""R2RML -> SQL compiler. Semantics per W3C R2RML §11 ("Generated RDF"), verified by running
the emitted SQL against SQLite and comparing the produced triple set.
"""
import sqlite3

import pytest

from ontoforge.compiler import compile_mapping, CompileError
from ontoforge.dialects import DatabricksDialect, SQLiteDialect, register_functions, XSD
from ontoforge.r2rml import parse_r2rml

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
EX = "http://example.com/ns#"
PREFIXES = """
@prefix rr:  <http://www.w3.org/ns/r2rml#> .
@prefix ex:  <http://example.com/ns#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
"""


def run(mapping_ttl, tables, column_types=None):
    """tables: {name: (columns, rows)} -> set of (s, p, o, object_type, datatype, lang)."""
    conn = sqlite3.connect(":memory:")
    register_functions(conn)
    for name, (cols, rows) in tables.items():
        conn.execute(f'CREATE TABLE "{name}" ({", ".join(cols)})')
        conn.executemany(f'INSERT INTO "{name}" VALUES ({", ".join("?" * len(rows[0]))})', rows)
    compiled = compile_mapping(parse_r2rml(PREFIXES + mapping_ttl), SQLiteDialect(), column_types=column_types)
    return set(conn.execute(compiled.sql).fetchall())


EMP = (["EMPNO", "ENAME", "DEPTNO", "SAL"], [(7369, "SMITH", 10, 800.5), (7499, "ALLEN", 20, None), (7521, "WARD", None, 1250)])
DEPT = (["DEPTNO", "DNAME"], [(10, "SALES"), (20, "RESEARCH")])


def test_class_produces_rdf_type_triples():  # §11.3 rr:class
    got = run("""
    <#Emp> a rr:TriplesMap ; rr:logicalTable [ rr:tableName "EMP" ] ;
        rr:subjectMap [ rr:template "http://d/emp/{EMPNO}" ; rr:class ex:Employee ] .
    """, {"EMP": EMP})
    assert got == {(f"http://d/emp/{n}", RDF_TYPE, EX + "Employee", "iri", None, None) for n in (7369, 7499, 7521)}


def test_column_object_is_plain_literal():
    got = run("""
    <#Emp> a rr:TriplesMap ; rr:logicalTable [ rr:tableName "EMP" ] ;
        rr:subjectMap [ rr:template "http://d/emp/{EMPNO}" ] ;
        rr:predicateObjectMap [ rr:predicate ex:name ; rr:objectMap [ rr:column "ENAME" ] ] .
    """, {"EMP": EMP})
    assert ("http://d/emp/7369", EX + "name", "SMITH", "literal", None, None) in got
    assert len(got) == 3


def test_null_column_produces_no_triple():  # §11.4: NULL -> no RDF term -> no triple
    got = run("""
    <#Emp> a rr:TriplesMap ; rr:logicalTable [ rr:tableName "EMP" ] ;
        rr:subjectMap [ rr:template "http://d/emp/{EMPNO}" ] ;
        rr:predicateObjectMap [ rr:predicate ex:sal ; rr:objectMap [ rr:column "SAL" ] ] .
    """, {"EMP": EMP})
    assert {r[0] for r in got} == {"http://d/emp/7369", "http://d/emp/7521"}


def test_iri_template_values_are_percent_encoded():  # §7.3 IRI-safe version of column value
    got = run("""
    <#D> a rr:TriplesMap ; rr:logicalTable [ rr:tableName "DEPT" ] ;
        rr:subjectMap [ rr:template "http://d/dept/{DNAME}" ; rr:class ex:Dept ] .
    """, {"DEPT": (["DNAME"], [("R & D",), ("Sales/EU",)])})
    assert {r[0] for r in got} == {"http://d/dept/R%20%26%20D", "http://d/dept/Sales%2FEU"}


def test_literal_template_is_not_encoded_and_carries_language():
    got = run("""
    <#Emp> a rr:TriplesMap ; rr:logicalTable [ rr:tableName "EMP" ] ;
        rr:subjectMap [ rr:template "http://d/emp/{EMPNO}" ] ;
        rr:predicateObjectMap [ rr:predicate ex:label ;
            rr:objectMap [ rr:template "{ENAME} #{EMPNO}" ; rr:language "en" ] ] .
    """, {"EMP": EMP})
    assert ("http://d/emp/7369", EX + "label", "SMITH #7369", "literal", None, "en") in got


def test_explicit_datatype_is_emitted():
    got = run("""
    <#Emp> a rr:TriplesMap ; rr:logicalTable [ rr:tableName "EMP" ] ;
        rr:subjectMap [ rr:template "http://d/emp/{EMPNO}" ] ;
        rr:predicateObjectMap [ rr:predicate ex:sal ; rr:objectMap [ rr:column "SAL" ; rr:datatype xsd:decimal ] ] .
    """, {"EMP": EMP})
    assert ("http://d/emp/7369", EX + "sal", "800.5", "literal", XSD + "decimal", None) in got


def test_natural_datatype_from_column_type_resolver():  # §10.2 natural mapping
    resolver = lambda lt, col: {"EMPNO": "INTEGER", "SAL": "DECIMAL(10,2)"}.get(col)
    got = run("""
    <#Emp> a rr:TriplesMap ; rr:logicalTable [ rr:tableName "EMP" ] ;
        rr:subjectMap [ rr:template "http://d/emp/{EMPNO}" ] ;
        rr:predicateObjectMap [ rr:predicate ex:no ; rr:objectMap [ rr:column "EMPNO" ] ] ;
        rr:predicateObjectMap [ rr:predicate ex:name ; rr:objectMap [ rr:column "ENAME" ] ] .
    """, {"EMP": EMP}, column_types=resolver)
    assert ("http://d/emp/7369", EX + "no", "7369", "literal", XSD + "integer", None) in got
    assert ("http://d/emp/7369", EX + "name", "SMITH", "literal", None, None) in got


def test_referencing_object_map_joins_child_to_parent():  # §8, §11.5
    got = run("""
    <#Emp> a rr:TriplesMap ; rr:logicalTable [ rr:tableName "EMP" ] ;
        rr:subjectMap [ rr:template "http://d/emp/{EMPNO}" ] ;
        rr:predicateObjectMap [ rr:predicate ex:dept ;
            rr:objectMap [ rr:parentTriplesMap <#Dept> ;
                           rr:joinCondition [ rr:child "DEPTNO" ; rr:parent "DEPTNO" ] ] ] .
    <#Dept> a rr:TriplesMap ; rr:logicalTable [ rr:tableName "DEPT" ] ;
        rr:subjectMap [ rr:template "http://d/dept/{DEPTNO}" ] .
    """, {"EMP": EMP, "DEPT": DEPT})
    assert got == {
        ("http://d/emp/7369", EX + "dept", "http://d/dept/10", "iri", None, None),
        ("http://d/emp/7499", EX + "dept", "http://d/dept/20", "iri", None, None),
    }  # WARD has NULL DEPTNO -> no join -> no triple


def test_referencing_object_map_without_join_uses_same_row():  # §8: no joinCondition => same logical table
    got = run("""
    <#Emp> a rr:TriplesMap ; rr:logicalTable [ rr:tableName "EMP" ] ;
        rr:subjectMap [ rr:template "http://d/emp/{EMPNO}" ] ;
        rr:predicateObjectMap [ rr:predicate ex:self ; rr:objectMap [ rr:parentTriplesMap <#Emp2> ] ] .
    <#Emp2> a rr:TriplesMap ; rr:logicalTable [ rr:tableName "EMP" ] ;
        rr:subjectMap [ rr:template "http://d/person/{EMPNO}" ] .
    """, {"EMP": EMP})
    assert got == {(f"http://d/emp/{n}", EX + "self", f"http://d/person/{n}", "iri", None, None) for n in (7369, 7499, 7521)}


def test_sql_query_logical_table():  # §5.2
    got = run("""
    <#Q> a rr:TriplesMap ;
        rr:logicalTable [ rr:sqlQuery "SELECT EMPNO, ENAME FROM EMP WHERE DEPTNO = 10" ] ;
        rr:subjectMap [ rr:template "http://d/emp/{EMPNO}" ; rr:class ex:SalesRep ] .
    """, {"EMP": EMP})
    assert {r[0] for r in got} == {"http://d/emp/7369"}


def test_blank_node_subject_and_constant_object():
    got = run("""
    <#Emp> a rr:TriplesMap ; rr:logicalTable [ rr:tableName "EMP" ] ;
        rr:subjectMap [ rr:column "EMPNO" ; rr:termType rr:BlankNode ] ;
        rr:predicateObjectMap [ rr:predicate ex:status ; rr:object "active" ] .
    """, {"EMP": EMP})
    assert ("_:7369", EX + "status", "active", "literal", None, None) in got


def test_multiple_predicates_fan_out():
    got = run("""
    <#Emp> a rr:TriplesMap ; rr:logicalTable [ rr:tableName "EMP" ] ;
        rr:subjectMap [ rr:template "http://d/emp/{EMPNO}" ] ;
        rr:predicateObjectMap [ rr:predicate ex:name, ex:label ; rr:objectMap [ rr:column "ENAME" ] ] .
    """, {"EMP": EMP})
    assert {r[1] for r in got} == {EX + "name", EX + "label"} and len(got) == 6


def test_sql_query_with_statement_separator_is_rejected():
    with pytest.raises(CompileError, match=";"):
        compile_mapping(parse_r2rml(PREFIXES + """
        <#Q> a rr:TriplesMap ; rr:logicalTable [ rr:sqlQuery "SELECT 1; DROP TABLE EMP" ] ;
            rr:subjectMap [ rr:template "http://d/{x}" ] .
        """), SQLiteDialect())


def test_databricks_sql_shape():
    compiled = compile_mapping(parse_r2rml(PREFIXES + """
    <#Emp> a rr:TriplesMap ; rr:logicalTable [ rr:tableName "main.hr.emp" ] ;
        rr:subjectMap [ rr:template "http://d/emp/{EMPNO}" ; rr:class ex:Employee ] ;
        rr:predicateObjectMap [ rr:predicate ex:name ; rr:objectMap [ rr:column "ENAME" ] ] .
    """), DatabricksDialect())
    assert len(compiled.selects) == 2
    assert "`main`.`hr`.`emp`" in compiled.sql
    assert "concat('http://d/emp/', replace(url_encode(CAST(t.`EMPNO` AS STRING)), '+', '%20'))" in compiled.sql
    assert "UNION ALL" in compiled.sql
    assert "t.`EMPNO` IS NOT NULL" in compiled.sql
    assert compiled.columns == ("subject", "predicate", "object", "object_type", "datatype", "lang")
