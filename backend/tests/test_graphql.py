"""GraphQL schema generated from the ontology, resolved against the triple store."""
from graphql import graphql_sync, print_schema

from ontoforge.graphql import build_schema
from tests.hr_fixture import built_domain, BASE


def test_schema_sdl_reflects_ontology(db):
    reg, store, v = built_domain(db)
    sdl = print_schema(build_schema(reg, store, v.id))
    assert "type Employee" in sdl and "type Department" in sdl and "type Person" in sdl
    assert "worksIn: [Department!]!" in sdl and "salary: Float" in sdl and "hired: String" in sdl
    assert "employees(search: String, limit: Int" in sdl and "employee(id: String!): Employee" in sdl


def test_nested_query_resolves_relations(db):
    reg, store, v = built_domain(db)
    schema = build_schema(reg, store, v.id)
    result = graphql_sync(schema, '{ employees(search: "SMITH") { id name salary worksIn { id name } collaboratesWith { name } } }')
    assert result.errors is None, result.errors
    (smith,) = result.data["employees"]
    assert smith["id"] == BASE + "Employee/1" and smith["name"] == "SMITH" and smith["salary"] == 800.0
    assert smith["worksIn"] == [{"id": BASE + "Department/10", "name": "SALES"}]
    assert smith["collaboratesWith"] == [{"name": "ALLEN"}]


def test_lookup_by_id_and_inherited_fields(db):
    reg, store, v = built_domain(db)
    schema = build_schema(reg, store, v.id)
    result = graphql_sync(schema, 'query($id: String!) { employee(id: $id) { name types } department(id: "x") { id } }',
                          variable_values={"id": BASE + "Employee/2"})
    assert result.errors is None, result.errors
    assert result.data["employee"]["name"] == "ALLEN" and "http://d/hr#Employee" in result.data["employee"]["types"]
    assert result.data["department"] is None


def test_limit_and_type_filtering(db):
    reg, store, v = built_domain(db)
    schema = build_schema(reg, store, v.id)
    result = graphql_sync(schema, '{ employees(limit: 2) { id } departments { name } }')
    assert result.errors is None
    assert len(result.data["employees"]) == 2 and {d["name"] for d in result.data["departments"]} == {"SALES", "RESEARCH"}
