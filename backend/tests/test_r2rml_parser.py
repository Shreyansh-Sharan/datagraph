"""R2RML parsing: Turtle -> in-memory mapping model.

Behaviour is defined by the W3C R2RML Recommendation (https://www.w3.org/TR/r2rml/).
Section references in test names point at the spec.
"""
import pytest

from ontoforge.r2rml import parse_r2rml, MappingError
from ontoforge.r2rml.model import TermKind

PREFIXES = """
@prefix rr:  <http://www.w3.org/ns/r2rml#> .
@prefix ex:  <http://example.com/ns#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
"""


def parse(ttl: str):
    return parse_r2rml(PREFIXES + ttl)


def test_triples_map_with_table_name_and_class():  # §5.1, §6, §7.1
    m = parse("""
    <#Emp> a rr:TriplesMap ;
        rr:logicalTable [ rr:tableName "EMP" ] ;
        rr:subjectMap [ rr:template "http://data.example.com/emp/{EMPNO}" ; rr:class ex:Employee ] .
    """)
    tm = m.triples_maps["http://example.com/ns#Emp"] if "http://example.com/ns#Emp" in m.triples_maps else m.only()
    assert tm.logical_table.table_name == "EMP"
    assert tm.logical_table.sql_query is None
    assert tm.subject.template == "http://data.example.com/emp/{EMPNO}"
    assert tm.subject.term_kind == TermKind.IRI
    assert tm.classes == ("http://example.com/ns#Employee",)
    assert tm.predicate_object_maps == ()


def test_logical_table_with_sql_query():  # §5.2
    m = parse("""
    <#Q> a rr:TriplesMap ;
        rr:logicalTable [ rr:sqlQuery "SELECT EMPNO, ENAME FROM EMP WHERE DEPTNO = 10" ] ;
        rr:subjectMap [ rr:template "http://data.example.com/emp/{EMPNO}" ] .
    """)
    tm = m.only()
    assert tm.logical_table.table_name is None
    assert tm.logical_table.sql_query == "SELECT EMPNO, ENAME FROM EMP WHERE DEPTNO = 10"


def test_predicate_and_object_shortcuts():  # §6.2 constant shortcut properties
    m = parse("""
    <#Emp> a rr:TriplesMap ;
        rr:logicalTable [ rr:tableName "EMP" ] ;
        rr:subjectMap [ rr:template "http://data.example.com/emp/{EMPNO}" ] ;
        rr:predicateObjectMap [ rr:predicate ex:name ; rr:objectMap [ rr:column "ENAME" ] ] .
    """)
    (pom,) = m.only().predicate_object_maps
    (pred,) = pom.predicates
    (obj,) = pom.objects
    assert pred.constant == "http://example.com/ns#name"
    assert pred.term_kind == TermKind.IRI
    assert obj.column == "ENAME"
    assert obj.term_kind == TermKind.LITERAL          # §7.4: column-valued object map defaults to literal
    assert obj.datatype is None and obj.language is None


def test_template_object_map_defaults_to_iri_and_datatype_forces_literal():  # §7.4
    m = parse("""
    <#Emp> a rr:TriplesMap ;
        rr:logicalTable [ rr:tableName "EMP" ] ;
        rr:subjectMap [ rr:template "http://data.example.com/emp/{EMPNO}" ] ;
        rr:predicateObjectMap [
            rr:predicate ex:dept ;
            rr:objectMap [ rr:template "http://data.example.com/dept/{DEPTNO}" ] ] ;
        rr:predicateObjectMap [
            rr:predicate ex:salary ;
            rr:objectMap [ rr:column "SAL" ; rr:datatype xsd:decimal ] ] ;
        rr:predicateObjectMap [
            rr:predicate ex:label ;
            rr:objectMap [ rr:template "{ENAME} ({EMPNO})" ; rr:language "en" ] ] .
    """)
    poms = {p.predicates[0].constant.rsplit("#", 1)[1]: p.objects[0] for p in m.only().predicate_object_maps}
    assert poms["dept"].term_kind == TermKind.IRI
    assert poms["salary"].term_kind == TermKind.LITERAL
    assert poms["salary"].datatype == "http://www.w3.org/2001/XMLSchema#decimal"
    assert poms["label"].term_kind == TermKind.LITERAL
    assert poms["label"].language == "en"


def test_explicit_term_type_blank_node():  # §7.4 rr:termType
    m = parse("""
    <#Emp> a rr:TriplesMap ;
        rr:logicalTable [ rr:tableName "EMP" ] ;
        rr:subjectMap [ rr:column "EMPNO" ; rr:termType rr:BlankNode ] .
    """)
    assert m.only().subject.term_kind == TermKind.BLANK_NODE


def test_constant_literal_object():  # §7.2 constant-valued term map
    m = parse("""
    <#Emp> a rr:TriplesMap ;
        rr:logicalTable [ rr:tableName "EMP" ] ;
        rr:subjectMap [ rr:template "http://data.example.com/emp/{EMPNO}" ] ;
        rr:predicateObjectMap [ rr:predicate ex:kind ; rr:object "permanent"@en ] .
    """)
    (obj,) = m.only().predicate_object_maps[0].objects
    assert obj.constant == "permanent"
    assert obj.term_kind == TermKind.LITERAL
    assert obj.language == "en"


def test_referencing_object_map_with_join_condition():  # §8
    m = parse("""
    <#Emp> a rr:TriplesMap ;
        rr:logicalTable [ rr:tableName "EMP" ] ;
        rr:subjectMap [ rr:template "http://data.example.com/emp/{EMPNO}" ] ;
        rr:predicateObjectMap [
            rr:predicate ex:department ;
            rr:objectMap [
                rr:parentTriplesMap <#Dept> ;
                rr:joinCondition [ rr:child "DEPTNO" ; rr:parent "DEPTNO" ] ] ] .
    <#Dept> a rr:TriplesMap ;
        rr:logicalTable [ rr:tableName "DEPT" ] ;
        rr:subjectMap [ rr:template "http://data.example.com/dept/{DEPTNO}" ] .
    """)
    emp = next(t for t in m.triples_maps.values() if t.logical_table.table_name == "EMP")
    (ref,) = emp.predicate_object_maps[0].objects
    assert ref.parent_triples_map.logical_table.table_name == "DEPT"
    assert ref.join_conditions == (("DEPTNO", "DEPTNO"),)


def test_multiple_predicates_in_one_predicate_object_map():  # §6.3 allows several predicate maps
    m = parse("""
    <#Emp> a rr:TriplesMap ;
        rr:logicalTable [ rr:tableName "EMP" ] ;
        rr:subjectMap [ rr:template "http://data.example.com/emp/{EMPNO}" ] ;
        rr:predicateObjectMap [ rr:predicate ex:name, ex:label ; rr:objectMap [ rr:column "ENAME" ] ] .
    """)
    (pom,) = m.only().predicate_object_maps
    assert sorted(p.constant for p in pom.predicates) == [
        "http://example.com/ns#label", "http://example.com/ns#name"]


def test_missing_logical_table_is_an_error():  # §5: exactly one logical table required
    with pytest.raises(MappingError, match="logicalTable"):
        parse("""
        <#Bad> a rr:TriplesMap ;
            rr:subjectMap [ rr:template "http://x/{A}" ] .
        """)


def test_term_map_must_have_exactly_one_value_source():  # §7: exactly one of constant/column/template
    with pytest.raises(MappingError, match="exactly one"):
        parse("""
        <#Bad> a rr:TriplesMap ;
            rr:logicalTable [ rr:tableName "T" ] ;
            rr:subjectMap [ rr:template "http://x/{A}" ; rr:column "A" ] .
        """)
