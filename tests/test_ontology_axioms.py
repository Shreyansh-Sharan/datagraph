"""OWL 2 property characteristics, axioms and class restrictions across the stack."""
from graphql import print_schema
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF

from ontoforge.graphql import build_schema
from ontoforge.ontology import DatatypeProperty, ObjectProperty, OntoClass, Ontology, Restriction, XSD
from ontoforge.reasoning import infer_triples, generate_shapes, Reasoner
from tests.hr_fixture import built_domain, ontology, BASE, EX


def rich() -> Ontology:
    o = ontology()
    o.object_properties[EX + "reportsTo"] = ObjectProperty(
        EX + "reportsTo", "reports to", domain=EX + "Employee", range=EX + "Employee", inverse_of=EX + "manages",
        characteristics=("functional", "transitive", "asymmetric"))
    o.object_properties[EX + "collaboratesWith"] = ObjectProperty(
        EX + "collaboratesWith", "collaborates with", domain=EX + "Employee", range=EX + "Employee",
        characteristics=("symmetric",), sub_property_of=(EX + "knows",))
    o.add_object_property(ObjectProperty(EX + "knows", "knows", domain=EX + "Person", range=EX + "Person"))
    o.add_object_property(ObjectProperty(EX + "hasMember", "has member", domain=EX + "Department", range=EX + "Employee",
                                         inverse_of=EX + "worksIn"))
    o.add_object_property(ObjectProperty(EX + "colleagueOf", "colleague of", domain=EX + "Employee", range=EX + "Employee",
                                         chain=((EX + "worksIn", EX + "hasMember"),)))
    o.add_class(OntoClass(EX + "Contractor", "Contractor", parents=(EX + "Person",), disjoint_with=(EX + "Employee",)))
    o.add_class(OntoClass(EX + "Staff", "Staff", equivalent_to=(EX + "Employee",)))
    o.classes[EX + "Employee"] = OntoClass(EX + "Employee", "Employee", parents=(EX + "Person",), restrictions=(
        Restriction(EX + "worksIn", "min", 1), Restriction(EX + "worksIn", "max", 1),
        Restriction(EX + "name", "exactly", 1), Restriction(EX + "reportsTo", "only", EX + "Employee"),
        Restriction(EX + "salary", "some", XSD + "decimal")))
    o.datatype_properties[EX + "name"] = DatatypeProperty(EX + "name", "name", range=XSD + "string", functional=True)
    return o


def test_axioms_round_trip_through_owl():
    o = rich()
    again = Ontology.from_turtle(o.to_turtle())
    assert again == o
    ttl = o.to_turtle()
    for token in ("owl:FunctionalProperty", "owl:TransitiveProperty", "owl:SymmetricProperty", "owl:AsymmetricProperty",
                  "rdfs:subPropertyOf", "owl:propertyChainAxiom", "owl:disjointWith", "owl:equivalentClass",
                  "owl:minCardinality", "owl:maxCardinality", "owl:cardinality", "owl:allValuesFrom", "owl:someValuesFrom"):
        assert token in ttl, token


def test_dict_round_trip_keeps_axioms():
    o = rich()
    assert Ontology.from_dict(o.to_dict()) == o


def test_checks_catch_bad_axioms():
    o = rich()
    o.classes[EX + "Employee"] = OntoClass(EX + "Employee", "Employee", parents=(EX + "Person",),
                                          restrictions=(Restriction(EX + "ghost", "min", 1),), disjoint_with=(EX + "Person",))
    o.object_properties[EX + "reportsTo"] = ObjectProperty(EX + "reportsTo", "reports to", domain=EX + "Employee",
                                                            range=EX + "Employee", characteristics=("bogus",))
    codes = {(i.code, i.subject) for i in o.check()}
    assert ("unknown-restriction-property", EX + "Employee") in codes
    assert ("disjoint-with-ancestor", EX + "Employee") in codes
    assert ("unknown-characteristic", EX + "reportsTo") in codes


def test_shapes_reflect_cardinality_and_functional():
    ttl = generate_shapes(rich())
    g = Graph().parse(data=ttl, format="turtle")
    SH = Namespace("http://www.w3.org/ns/shacl#")
    shapes = {(str(g.value(ps, SH.path)), str(g.value(ps, SH.minCount)), str(g.value(ps, SH.maxCount)))
              for ps in g.objects(URIRef(EX + "EmployeeShape"), SH.property)}
    assert (EX + "worksIn", "1", "1") in shapes
    assert (EX + "reportsTo", "None", "1") in shapes      # functional -> maxCount 1
    assert any(p == EX + "name" and mx == "1" for p, mn, mx in shapes)


def test_owl_rl_uses_characteristics_and_axioms():
    o = rich()
    data = Graph()
    E = Namespace(BASE + "Employee/")
    data.add((E["3"], URIRef(EX + "reportsTo"), E["2"]))
    data.add((E["2"], URIRef(EX + "reportsTo"), E["1"]))
    data.add((E["1"], URIRef(EX + "collaboratesWith"), E["2"]))
    data.add((E["1"], URIRef(EX + "worksIn"), URIRef(BASE + "Department/10")))
    data.add((E["5"], URIRef(EX + "worksIn"), URIRef(BASE + "Department/10")))
    data.add((E["9"], RDF.type, URIRef(EX + "Employee")))
    data.add((E["9"], RDF.type, URIRef(EX + "Contractor")))
    tbox = Graph().parse(data=o.to_turtle(), format="turtle")
    new = infer_triples(tbox, data)
    triples = {(str(s), str(p), str(ob)) for s, p, ob in new}
    e = lambda n: str(E[n])
    assert (e("3"), EX + "reportsTo", e("1")) in triples                  # transitive
    assert (e("2"), EX + "collaboratesWith", e("1")) in triples           # symmetric
    assert (e("1"), EX + "knows", e("2")) in triples                      # subPropertyOf
    assert (e("1"), EX + "manages", e("2")) in triples                    # inverse
    assert (e("1"), EX + "colleagueOf", e("5")) in triples                # property chain
    assert (e("3"), str(RDF.type), EX + "Staff") in triples               # equivalentClass (via range typing)
    assert not any(s.startswith(("1", "0")) and len(s) < 3 for s, _, _ in triples)   # no literal-subject noise
    inconsistent = {str(s) for s, p, ob in new if p == RDF.type and ob == OWL.Nothing}
    assert e("9") in inconsistent                                          # disjoint classes


def test_reasoner_reports_inconsistencies(db):
    reg, store, v = built_domain(db)
    o = rich()
    reg.update_content(v.id, actor="alice", ontology_ttl=o.to_turtle())
    store.add_inferred(v.id, [])
    store.replace(v.id, list(store.iter_triples(v.id)) + [(BASE + "Employee/1", str(RDF.type), EX + "Contractor", "iri", None, None)])
    report = Reasoner(reg, store).owl_rl(v.id)
    assert report.inconsistent == [BASE + "Employee/1"]


def test_functional_object_property_is_single_valued_in_graphql(db):
    reg, store, v = built_domain(db)
    reg.update_content(v.id, actor="alice", ontology_ttl=rich().to_turtle())
    sdl = print_schema(build_schema(reg, store, v.id))
    assert "reportsTo: Employee\n" in sdl and "worksIn: [Department!]!" in sdl
