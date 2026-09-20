import pytest
"""Graph browsing parity: search match modes and fields, an overview subgraph, raw triple paging."""
from ontoforge.compiler import RDF_TYPE
from tests.hr_fixture import built_domain, BASE, EX


def test_search_match_modes_and_fields(db):
    reg, store, v = built_domain(db)
    assert [h.label for h in store.search(v.id, "SMITH", match="exact")] == ["SMITH"]
    assert store.search(v.id, "SMI", match="exact") == []
    assert {h.label for h in store.search(v.id, "A", match="starts_with")} == {"ALLEN"}
    ends = {h.label for h in store.search(v.id, "H", match="ends_with")}
    assert "SMITH" in ends and "RESEARCH" in ends and "ALLEN" not in ends
    assert {h.label for h in store.search(v.id, "Employee/2", field="iri")} == {"ALLEN"}
    assert store.search(v.id, "SMITH", field="iri") == []              # labels are not searched in iri mode
    assert {h.label for h in store.search(v.id, "employee/3", field="iri", match="ends_with")} == {"WARD"}


def test_overview_returns_a_balanced_sample_of_relationships(db):
    reg, store, v = built_domain(db)
    sub = store.overview(v.id, limit=4)
    assert 0 < len(sub.edges) <= 4
    preds = {e.predicate for e in sub.edges}
    assert len(preds) >= 2                                             # not just the first predicate's rows
    assert {n.iri for n in sub.nodes} >= {e.source for e in sub.edges} | {e.target for e in sub.edges}
    assert all(n.types for n in sub.nodes)


def test_triples_paging_and_filters(db):
    reg, store, v = built_domain(db)
    page = store.triples(v.id, limit=5, offset=0)
    assert page.total > 5 and len(page.rows) == 5 and set(page.rows[0]) >= {"subject", "predicate", "object", "object_type", "inferred"}
    typed = store.triples(v.id, predicate=RDF_TYPE, limit=100)
    assert typed.total == 6 and all(r["predicate"] == RDF_TYPE for r in typed.rows)
    smith = store.triples(v.id, subject=BASE + "Employee/1", limit=100)
    assert smith.total >= 5 and all(r["subject"] == BASE + "Employee/1" for r in smith.rows)
    contains = store.triples(v.id, text="SMI", limit=100)
    assert contains.total == 1 and contains.rows[0]["object"] == "SMITH"
    assert store.triples(v.id, limit=5, offset=page.total).rows == []


def test_triples_sort_by_column_and_direction(db):
    reg, store, v = built_domain(db)
    by_obj = store.triples(v.id, limit=200, sort="object", direction="desc").rows
    objs = [r["object"] for r in by_obj]
    assert objs == sorted(objs, reverse=True)
    by_pred = store.triples(v.id, limit=200, sort="predicate").rows
    preds = [r["predicate"] for r in by_pred]
    assert preds == sorted(preds)
    with pytest.raises(ValueError):
        store.triples(v.id, sort="object; drop table triples")
    with pytest.raises(ValueError):
        store.triples(v.id, direction="sideways")
