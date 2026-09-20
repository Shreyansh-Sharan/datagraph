"""The Postgres dialect + catalog, verified by executing compiled SQL on a live Postgres."""
from ontoforge.catalog import PostgresCatalog
from ontoforge.compiler import compile_mapping
from ontoforge.dialects import PostgresDialect, XSD
from ontoforge.r2rml import parse_r2rml, LogicalTable

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
EX = "http://example.com/ns#"
PREFIXES = """
@prefix rr:  <http://www.w3.org/ns/r2rml#> .
@prefix ex:  <http://example.com/ns#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
"""


def seed(db):
    with db.transaction() as cur:
        cur.execute('CREATE TABLE emp (empno int, ename text, deptno int, sal numeric(10,2))')
        cur.execute('CREATE TABLE dept (deptno int, dname text)')
        cur.executemany('INSERT INTO emp VALUES (%s, %s, %s, %s)',
                        [(7369, "SMITH", 10, 800.5), (7499, "ALLEN", 20, None), (7521, "R & D guy", None, 1250)])
        cur.executemany('INSERT INTO dept VALUES (%s, %s)', [(10, "SALES"), (20, "RESEARCH")])


def run(db, ttl, column_types=None):
    compiled = compile_mapping(parse_r2rml(PREFIXES + ttl), PostgresDialect(), column_types=column_types)
    with db.transaction() as cur:
        cur.execute(PostgresDialect().setup_sql())
        return set(cur.execute(compiled.sql).fetchall())


def test_dialect_primitives():
    d = PostgresDialect()
    assert d.quote_identifier('a"b') == '"a""b"'
    assert d.string_literal("it's") == "'it''s'"
    assert d.concat(["'a'", '"b"']) == "('a' || \"b\")"
    assert d.null_text() == "CAST(NULL AS TEXT)"


def test_class_and_join_and_null_semantics_on_postgres(db):
    seed(db)
    got = run(db, """
    <#Emp> a rr:TriplesMap ; rr:logicalTable [ rr:tableName "emp" ] ;
        rr:subjectMap [ rr:template "http://d/emp/{empno}" ; rr:class ex:Employee ] ;
        rr:predicateObjectMap [ rr:predicate ex:sal ; rr:objectMap [ rr:column "sal" ; rr:datatype xsd:decimal ] ] ;
        rr:predicateObjectMap [ rr:predicate ex:dept ;
            rr:objectMap [ rr:parentTriplesMap <#Dept> ; rr:joinCondition [ rr:child "deptno" ; rr:parent "deptno" ] ] ] .
    <#Dept> a rr:TriplesMap ; rr:logicalTable [ rr:tableName "dept" ] ;
        rr:subjectMap [ rr:template "http://d/dept/{deptno}" ] .
    """)
    assert ("http://d/emp/7369", RDF_TYPE, EX + "Employee", "iri", None, None) in got
    assert ("http://d/emp/7369", EX + "sal", "800.50", "literal", XSD + "decimal", None) in got
    assert ("http://d/emp/7369", EX + "dept", "http://d/dept/10", "iri", None, None) in got
    assert not any(r[0] == "http://d/emp/7499" and r[1] == EX + "sal" for r in got)   # NULL sal
    assert not any(r[0] == "http://d/emp/7521" and r[1] == EX + "dept" for r in got)  # NULL deptno


def test_iri_encoding_function_handles_unicode_and_reserved_chars(db):
    seed(db)
    with db.transaction() as cur:
        cur.execute('INSERT INTO dept VALUES (30, %s)', ("Zürich/HQ",))
    got = run(db, """
    <#D> a rr:TriplesMap ; rr:logicalTable [ rr:tableName "dept" ] ;
        rr:subjectMap [ rr:template "http://d/dept/{dname}" ; rr:class ex:Dept ] .
    """)
    subjects = {r[0] for r in got}
    assert "http://d/dept/Z%C3%BCrich%2FHQ" in subjects
    assert "http://d/dept/SALES" in subjects


def test_postgres_catalog_feeds_natural_datatypes(db):
    seed(db)
    resolve = PostgresCatalog(db).resolver()
    assert resolve(LogicalTable(table_name="emp"), "EMPNO") == "integer"
    got = run(db, """
    <#Emp> a rr:TriplesMap ; rr:logicalTable [ rr:tableName "emp" ] ;
        rr:subjectMap [ rr:template "http://d/emp/{empno}" ] ;
        rr:predicateObjectMap [ rr:predicate ex:no ; rr:objectMap [ rr:column "empno" ] ] ;
        rr:predicateObjectMap [ rr:predicate ex:sal ; rr:objectMap [ rr:column "sal" ] ] .
    """, column_types=resolve)
    assert ("http://d/emp/7369", EX + "no", "7369", "literal", XSD + "integer", None) in got
    assert ("http://d/emp/7369", EX + "sal", "800.50", "literal", XSD + "decimal", None) in got
