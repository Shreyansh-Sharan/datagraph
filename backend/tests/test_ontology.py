"""Ontology model: classes, properties, hierarchy; OWL 2 (Turtle) round-trip; structural checks."""
from ontoforge.ontology import Ontology, OntoClass, ObjectProperty, DatatypeProperty, XSD

EX = "http://d/hr#"


def hr() -> Ontology:
    o = Ontology(iri="http://d/hr", label="HR")
    o.add_class(OntoClass(EX + "Person", label="Person"))
    o.add_class(OntoClass(EX + "Employee", label="Employee", parents=(EX + "Person",)))
    o.add_class(OntoClass(EX + "Manager", label="Manager", parents=(EX + "Employee",)))
    o.add_class(OntoClass(EX + "Department", label="Department", description="An org unit"))
    o.add_object_property(ObjectProperty(EX + "worksIn", label="works in", domain=EX + "Employee", range=EX + "Department"))
    o.add_object_property(ObjectProperty(EX + "manages", label="manages", domain=EX + "Manager", range=EX + "Department",
                                         inverse_of=EX + "managedBy"))
    o.add_datatype_property(DatatypeProperty(EX + "name", label="name", domain=EX + "Person", range=XSD + "string"))
    o.add_datatype_property(DatatypeProperty(EX + "salary", label="salary", domain=EX + "Employee", range=XSD + "decimal"))
    return o


def test_turtle_round_trip_preserves_model():
    o = hr()
    again = Ontology.from_turtle(o.to_turtle())
    assert again == o


def test_turtle_output_is_owl():
    ttl = hr().to_turtle()
    assert "owl:Class" in ttl and "owl:ObjectProperty" in ttl and "owl:DatatypeProperty" in ttl
    assert "rdfs:subClassOf" in ttl and "owl:inverseOf" in ttl


def test_parse_external_owl_with_hierarchy_and_ranges():
    o = Ontology.from_turtle("""
    @prefix owl: <http://www.w3.org/2002/07/owl#> . @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> . @prefix : <http://ex/#> .
    <http://ex/> a owl:Ontology ; rdfs:label "Ex" .
    :Animal a owl:Class ; rdfs:label "Animal" .
    :Dog a owl:Class ; rdfs:subClassOf :Animal .
    :owner a owl:ObjectProperty ; rdfs:domain :Dog ; rdfs:range :Person .
    :Person a owl:Class .
    :age a owl:DatatypeProperty ; rdfs:domain :Animal ; rdfs:range xsd:integer ; rdfs:comment "years" .
    """)
    assert o.iri == "http://ex/" and o.label == "Ex"
    assert o.classes["http://ex/#Dog"].parents == ("http://ex/#Animal",)
    assert o.classes["http://ex/#Dog"].label == "Dog"  # falls back to local name
    assert o.object_properties["http://ex/#owner"].range == "http://ex/#Person"
    assert o.datatype_properties["http://ex/#age"].description == "years"


def test_ancestors_descendants_and_inherited_properties():
    o = hr()
    assert o.ancestors(EX + "Manager") == (EX + "Employee", EX + "Person")
    assert set(o.descendants(EX + "Person")) == {EX + "Employee", EX + "Manager"}
    props = {p.iri for p in o.properties_of(EX + "Manager")}
    assert props == {EX + "worksIn", EX + "manages", EX + "name", EX + "salary"}


def test_structural_checks_flag_common_pitfalls():
    o = hr()
    o.add_class(OntoClass(EX + "Orphan"))                                                      # no label
    o.add_object_property(ObjectProperty(EX + "broken", domain=EX + "Employee", range=EX + "Nope"))  # unknown range
    o.add_datatype_property(DatatypeProperty(EX + "floating"))                                 # no domain
    o.classes[EX + "Person"] = OntoClass(EX + "Person", label="Person", parents=(EX + "Manager",))  # cycle
    codes = {(i.code, i.subject) for i in o.check()}
    assert ("missing-label", EX + "Orphan") in codes
    assert ("unknown-range", EX + "broken") in codes
    assert ("missing-domain", EX + "floating") in codes
    assert any(c == "subclass-cycle" for c, _ in codes)


def test_local_name_and_iri_minting():
    o = Ontology(iri="http://d/hr")
    c = o.new_class("Cost Centre")
    assert c.iri == "http://d/hr#CostCentre" and c.label == "Cost Centre"
    assert o.local_name(c.iri) == "CostCentre"


def test_to_dict_and_from_dict():
    o = hr()
    assert Ontology.from_dict(o.to_dict()) == o
