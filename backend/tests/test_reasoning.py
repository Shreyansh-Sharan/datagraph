"""OWL 2 RL closure and SHACL validation over a built domain."""
from ontoforge.compiler import RDF_TYPE
from ontoforge.reasoning import Reasoner, generate_shapes
from ontoforge.ontology import Ontology

from tests.hr_fixture import built_domain, ontology, EX, BASE


def test_owl_rl_infers_superclass_and_inverse_and_range_types(db):
    reg, store, v = built_domain(db)
    report = Reasoner(reg, store).owl_rl(v.id)
    assert report.inferred > 0 and store.count(v.id, inferred=True) == report.inferred
    smith = store.describe(v.id, BASE + "Employee/1")
    assert EX + "Person" in smith.types                                              # rdfs:subClassOf
    assert (EX + "manages", BASE + "Employee/2") in {(r.predicate, r.target) for r in smith.outgoing}  # owl:inverseOf
    ghost_dept = store.describe(v.id, BASE + "Department/99")
    assert EX + "Department" in ghost_dept.types                                     # rdfs:range typing


def test_owl_rl_is_idempotent_and_skips_trivial_axioms(db):
    reg, store, v = built_domain(db)
    r = Reasoner(reg, store)
    first = r.owl_rl(v.id).inferred
    assert r.owl_rl(v.id).inferred == first
    rows = list(store.iter_triples(v.id, inferred=True))
    assert not any(o.endswith("owl#Thing") or o.endswith("rdf-schema#Resource") for _, p, o, *_ in rows if p == RDF_TYPE)
    assert not any(p.endswith("owl#sameAs") for _, p, *_ in rows)


def test_shapes_are_generated_from_ontology():
    ttl = generate_shapes(ontology())
    assert "sh:NodeShape" in ttl and "sh:targetClass" in ttl
    assert "sh:datatype" in ttl and "sh:class" in ttl


def test_shacl_validation_reports_range_violations(db):
    reg, store, v = built_domain(db)
    report = Reasoner(reg, store).validate(v.id)
    assert report.conforms is False
    focus = {(r.focus, r.path) for r in report.results}
    assert (BASE + "Employee/4", EX + "worksIn") in focus  # Department/99 has no rdf:type Department
    assert all(r.message for r in report.results)


def test_shacl_passes_after_inference_types_the_missing_department(db):
    reg, store, v = built_domain(db)
    r = Reasoner(reg, store)
    r.owl_rl(v.id)
    assert r.validate(v.id).conforms is True


def test_inferred_triples_never_have_blank_node_subjects(db):
    reg, store, v = built_domain(db)
    from tests.test_ontology_axioms import rich
    reg.update_content(v.id, actor="alice", ontology_ttl=rich().to_turtle())   # restrictions introduce blank nodes in the TBox
    Reasoner(reg, store).owl_rl(v.id)
    assert not [r for r in store.iter_triples(v.id, inferred=True) if r[0].startswith("_:")]
