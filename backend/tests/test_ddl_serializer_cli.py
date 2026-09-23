"""Materialisation DDL, R2RML serialisation (round-trip), and the CLI."""
import subprocess
import sys

from ontoforge.compiler import compile_mapping
from ontoforge.dialects import DatabricksDialect, SQLiteDialect
from ontoforge.r2rml import parse_r2rml, serialize_r2rml

PREFIXES = """
@prefix rr:  <http://www.w3.org/ns/r2rml#> .
@prefix ex:  <http://example.com/ns#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
"""
MAPPING = PREFIXES + """
<#Emp> a rr:TriplesMap ; rr:logicalTable [ rr:tableName "main.hr.emp" ] ;
    rr:subjectMap [ rr:template "http://d/emp/{EMPNO}" ; rr:class ex:Employee ] ;
    rr:predicateObjectMap [ rr:predicate ex:name ; rr:objectMap [ rr:column "ENAME" ] ] ;
    rr:predicateObjectMap [ rr:predicate ex:sal ; rr:objectMap [ rr:column "SAL" ; rr:datatype xsd:decimal ] ] ;
    rr:predicateObjectMap [ rr:predicate ex:label ; rr:objectMap [ rr:template "{ENAME}" ; rr:language "en" ] ] ;
    rr:predicateObjectMap [ rr:predicate ex:dept ;
        rr:objectMap [ rr:parentTriplesMap <#Dept> ; rr:joinCondition [ rr:child "DEPTNO" ; rr:parent "DEPTNO" ] ] ] ;
    rr:predicateObjectMap [ rr:predicate ex:status ; rr:object "active"@en ] .
<#Dept> a rr:TriplesMap ; rr:logicalTable [ rr:sqlQuery "SELECT DEPTNO FROM main.hr.dept" ] ;
    rr:subjectMap [ rr:column "DEPTNO" ; rr:termType rr:BlankNode ] .
"""


# -- DDL -----------------------------------------------------------------------

def test_view_ddl_wraps_union_in_create_or_replace_view():
    c = compile_mapping(parse_r2rml(MAPPING), DatabricksDialect())
    ddl = c.view_ddl("main.kg.emp_triples")
    assert ddl.startswith("CREATE OR REPLACE VIEW `main`.`kg`.`emp_triples` AS\n")
    assert ddl.rstrip().endswith("IS NOT NULL")


def test_table_ddl_materialises_with_ctas():
    c = compile_mapping(parse_r2rml(MAPPING), DatabricksDialect())
    ddl = c.table_ddl("main.kg.emp_triples")
    assert ddl.startswith("CREATE OR REPLACE TABLE `main`.`kg`.`emp_triples` AS\n")


# -- serialiser ----------------------------------------------------------------

def test_serialised_mapping_reparses_to_equal_model():
    original = parse_r2rml(MAPPING)
    ttl = serialize_r2rml(original)
    again = parse_r2rml(ttl)
    assert again.triples_maps.keys() == original.triples_maps.keys()
    for iri, tm in original.triples_maps.items():
        assert again.triples_maps[iri] == tm


def test_serialised_mapping_compiles_to_identical_sql():
    original = parse_r2rml(MAPPING)
    again = parse_r2rml(serialize_r2rml(original))
    assert compile_mapping(again, SQLiteDialect()).sql == compile_mapping(original, SQLiteDialect()).sql


# -- CLI -----------------------------------------------------------------------

def test_cli_compiles_a_mapping_file(tmp_path):
    f = tmp_path / "m.ttl"
    f.write_text(MAPPING)
    r = subprocess.run([sys.executable, "-m", "ontoforge", "compile", str(f), "--dialect", "databricks"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "`main`.`hr`.`emp`" in r.stdout and "UNION ALL" in r.stdout


def test_cli_emits_view_ddl_when_target_given(tmp_path):
    f = tmp_path / "m.ttl"
    f.write_text(MAPPING)
    r = subprocess.run([sys.executable, "-m", "ontoforge", "compile", str(f), "--dialect", "databricks",
                        "--view", "main.kg.triples"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("CREATE OR REPLACE VIEW `main`.`kg`.`triples` AS")


def test_cli_reports_mapping_errors_with_nonzero_exit(tmp_path):
    f = tmp_path / "bad.ttl"
    f.write_text(PREFIXES + '<#B> a rr:TriplesMap ; rr:subjectMap [ rr:template "http://x/{A}" ] .')
    r = subprocess.run([sys.executable, "-m", "ontoforge", "compile", str(f)], capture_output=True, text=True)
    assert r.returncode == 2
    assert "logicalTable" in r.stderr
