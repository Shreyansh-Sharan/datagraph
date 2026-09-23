"""Triple store on Postgres + the build pipeline that fills it from a mapping spec."""
import pytest

from ontoforge.build import BuildPipeline, PostgresSource
from ontoforge.compiler import RDF_TYPE
from ontoforge.mapping import MappingSpec, ClassMapping, AttributeBinding, RelationMapping
from ontoforge.registry import Registry
from ontoforge.store import TripleStore

EX, BASE = "http://d/hr#", "http://d/hr/"


def seed(db):
    with db.transaction() as cur:
        cur.execute("CREATE TABLE emp (empno int, ename text, deptno int, sal numeric)")
        cur.executemany("INSERT INTO emp VALUES (%s,%s,%s,%s)", [(1, "SMITH", 10, 800), (2, "ALLEN", 20, None), (3, "WARD", None, 1250)])
        cur.execute("CREATE TABLE dept (deptno int, dname text)")
        cur.executemany("INSERT INTO dept VALUES (%s,%s)", [(10, "SALES"), (20, "RESEARCH")])
        cur.execute("CREATE TABLE collab (a int, b int)")
        cur.executemany("INSERT INTO collab VALUES (%s,%s)", [(1, 2), (2, 3)])


def spec(emp_table="emp") -> dict:
    return MappingSpec(base_iri=BASE, classes=(
        ClassMapping(EX + "Employee", table=emp_table, key_columns=("empno",),
                     attributes=(AttributeBinding(EX + "name", "ename"), AttributeBinding(EX + "salary", "sal"))),
        ClassMapping(EX + "Department", table="dept", key_columns=("deptno",), attributes=(AttributeBinding(EX + "name", "dname"),)),
    ), relations=(
        RelationMapping(EX + "worksIn", EX + "Employee", EX + "Department", target_key=("deptno",)),
        RelationMapping(EX + "collaboratesWith", EX + "Employee", EX + "Employee", table="collab", source_key=("a",), target_key=("b",)),
    )).to_dict()


@pytest.fixture
def env(db):
    seed(db)
    reg = Registry(db)
    d = reg.create_domain("hr", base_iri=BASE)
    v = reg.create_version(d.id, actor="alice")
    reg.update_content(v.id, actor="alice", mapping=spec())
    return reg, TripleStore(db), BuildPipeline(reg, TripleStore(db), PostgresSource(db)), v


def test_build_materialises_triples_and_records_run(env):
    reg, store, pipeline, v = env
    run = pipeline.run(v.id, actor="alice")
    assert run.status == "succeeded", run.error
    assert run.triple_count == store.count(v.id) > 0
    assert [s["name"] for s in run.steps] == ["compile", "prepare", "plan", "load", "finalize"]
    assert reg.get_version(v.id).r2rml_ttl and "r2rml" in reg.get_version(v.id).r2rml_ttl


def test_rebuild_replaces_rather_than_appends(env):
    _, store, pipeline, v = env
    first = pipeline.run(v.id, actor="alice").triple_count
    assert pipeline.run(v.id, actor="alice").triple_count == first == store.count(v.id)


def test_failed_build_keeps_previous_triples_and_records_error(env):
    reg, store, pipeline, v = env
    before = pipeline.run(v.id, actor="alice").triple_count
    reg.update_content(v.id, actor="alice", mapping=spec(emp_table="does_not_exist"))
    run = pipeline.run(v.id, actor="alice")
    assert run.status == "failed" and "does_not_exist" in run.error
    assert store.count(v.id) == before


def test_type_and_predicate_inventory(env):
    _, store, pipeline, v = env
    pipeline.run(v.id, actor="alice")
    assert dict(store.type_inventory(v.id)) == {EX + "Employee": 3, EX + "Department": 2}
    preds = dict(store.predicate_inventory(v.id))
    assert preds[EX + "worksIn"] == 2 and preds[EX + "collaboratesWith"] == 2 and preds[RDF_TYPE] == 5


def test_search_finds_entities_by_literal_or_iri(env):
    _, store, pipeline, v = env
    pipeline.run(v.id, actor="alice")
    hits = store.search(v.id, "smi")
    assert [h.iri for h in hits] == [BASE + "Employee/1"]
    assert hits[0].types == (EX + "Employee",) and hits[0].label == "SMITH"
    assert [h.iri for h in store.search(v.id, "Department/2")] == [BASE + "Department/20"]
    assert store.search(v.id, "s", type_iri=EX + "Department") and all(
        h.types == (EX + "Department",) for h in store.search(v.id, "s", type_iri=EX + "Department"))


def test_describe_entity(env):
    _, store, pipeline, v = env
    pipeline.run(v.id, actor="alice")
    e = store.describe(v.id, BASE + "Employee/1")
    assert e.types == (EX + "Employee",)
    assert {(a.predicate, a.value) for a in e.attributes} == {(EX + "name", "SMITH"), (EX + "salary", "800")}
    assert {(r.predicate, r.target) for r in e.outgoing} == {(EX + "worksIn", BASE + "Department/10"),
                                                            (EX + "collaboratesWith", BASE + "Employee/2")}
    assert store.describe(v.id, BASE + "Department/10").incoming[0].source == BASE + "Employee/1"
    assert store.describe(v.id, "http://nope") is None


def test_neighbourhood_expansion_by_depth(env):
    _, store, pipeline, v = env
    pipeline.run(v.id, actor="alice")
    one = store.neighbourhood(v.id, BASE + "Employee/1", depth=1)
    assert {n.iri for n in one.nodes} == {BASE + "Employee/1", BASE + "Employee/2", BASE + "Department/10"}
    two = store.neighbourhood(v.id, BASE + "Employee/1", depth=2)
    assert BASE + "Employee/3" in {n.iri for n in two.nodes} and BASE + "Department/20" in {n.iri for n in two.nodes}
    assert all(e.predicate for e in two.edges) and len(two.edges) >= 4


def test_inferred_triples_are_separable(env):
    _, store, pipeline, v = env
    pipeline.run(v.id, actor="alice")
    base = store.count(v.id)
    store.add_inferred(v.id, [(BASE + "Employee/1", RDF_TYPE, EX + "Person", "iri", None, None)])
    assert store.count(v.id) == base + 1 and store.count(v.id, inferred=True) == 1
    assert EX + "Person" in store.describe(v.id, BASE + "Employee/1").types
    store.clear_inferred(v.id)
    assert store.count(v.id) == base
    pipeline.run(v.id, actor="alice")
    assert store.count(v.id, inferred=True) == 0  # a rebuild drops stale inferences


def test_search_and_inventory_ignore_blank_node_subjects(env):
    _, store, pipeline, v = env
    pipeline.run(v.id, actor="alice")
    store.add_inferred(v.id, [("_:b1", EX + "name", "SMITHY", "literal", None, None), ("_:b1", RDF_TYPE, EX + "Employee", "iri", None, None)])
    assert [h.iri for h in store.search(v.id, "smith")] == [BASE + "Employee/1"]
    assert dict(store.type_inventory(v.id))[EX + "Employee"] == 3


def test_search_ranks_exact_then_prefix_then_contains(env):
    _, store, pipeline, v = env
    pipeline.run(v.id, actor="alice")
    store.add_inferred(v.id, [
        (BASE + "Department/50", EX + "name", "Cola", "literal", None, None),
        (BASE + "Department/51", EX + "name", "Cola Zero Sugar", "literal", None, None),
        (BASE + "Department/52", EX + "name", "Online Commerce (Coca-Cola)", "literal", None, None),
        (BASE + "Department/30", EX + "name", "Vanilla", "literal", None, None),
    ])
    hits = store.search(v.id, "cola")
    assert [h.label for h in hits][:3] == ["Cola", "Cola Zero Sugar", "Online Commerce (Coca-Cola)"]
    assert store.search(v.id, "col")[0].label == "Cola"


def test_counts_total_and_inferred_in_one_pass(env):
    _, store, pipeline, v = env
    pipeline.run(v.id, actor="alice")
    store.add_inferred(v.id, [(EX + "x", EX + "knows", EX + "y", "iri", None, None)])
    assert store.counts(v.id) == (store.count(v.id), store.count(v.id, inferred=True)) == (store.count(v.id), 1)


def test_a_build_keeps_its_source_to_itself(env):
    """One pipeline serves every worker thread, so a run must carry its source, not park it on self."""
    reg, store, pipeline, v = env
    pipeline.run(v.id, actor="alice")
    assert not hasattr(pipeline, "source"), "a per-build source on the shared pipeline crosses concurrent runs"


def test_each_build_loads_from_the_source_it_was_given(db):
    """One pipeline serves every domain, so the source must travel with the run, not on the object."""
    from ontoforge.build import BuildPipeline, PostgresSource
    from ontoforge.registry import Registry
    from ontoforge.store import TripleStore

    seed(db)
    reg, store = Registry(db), TripleStore(db)
    versions, engines = {}, {}
    for name in ("alpha", "beta"):
        d = reg.create_domain(name, base_iri=f"http://d/{name}/")
        ver = reg.create_version(d.id, actor="alice")
        reg.update_content(ver.id, actor="alice", mapping=spec())
        versions[name] = ver
        engines[name] = PostgresSource(db)

    pipeline = BuildPipeline(reg, store, lambda vid: next(engines[n] for n, v in versions.items() if v.id == vid))
    loaded: dict = {}
    original = pipeline._load_tables

    def record(version_id, compiled, plan, on_rows=None, source=None, cancelled=None):
        name = next(n for n, v in versions.items() if v.id == version_id)
        loaded[name] = source
        return original(version_id, compiled, plan, on_rows, source, cancelled)

    pipeline._load_tables = record
    for name in ("alpha", "beta"):
        assert pipeline.run(versions[name].id, actor="alice").status == "succeeded"
    assert loaded["alpha"] is engines["alpha"] and loaded["beta"] is engines["beta"]
