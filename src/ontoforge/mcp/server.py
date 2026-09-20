"""MCP server exposing GraphTools. Run over stdio with ``python -m ontoforge serve-mcp``."""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .tools import GraphTools

INSTRUCTIONS = (
    "You are connected to an ontoforge knowledge graph. Start with list_domains, then describe_ontology "
    "for the domain you need. Use search_entities / describe_entity for specific things, and "
    "get_graphql_schema + query_graphql for structured, nested questions."
)


def create_mcp_server(tools: GraphTools, name: str = "ontoforge") -> MCPServer:
    server = MCPServer(name, instructions=INSTRUCTIONS, version="0.1.0")

    @server.tool(description="List knowledge-graph domains with their served version and triple count.")
    def list_domains() -> list[dict]:
        return tools.list_domains()

    @server.tool(description="Select the domain that later tools use when 'domain' is omitted.")
    def select_domain(domain: str) -> dict:
        return tools.select_domain(domain)

    @server.tool(description="Versions of a domain with status, content flags and build state.")
    def list_domain_versions(domain: str | None = None) -> list[dict]:
        return tools.list_domain_versions(domain)

    @server.tool(description="Design readiness of a domain: ontology, mapping completion, build, drift.")
    def get_design_status(domain: str | None = None) -> dict:
        return tools.get_design_status(domain)

    @server.tool(description="Describe a domain's ontology: classes, attributes and relationships, in plain text.")
    def describe_ontology(domain: str | None = None) -> str:
        return tools.describe_ontology(domain)

    @server.tool(description="Triple counts and entity types for a domain's graph.")
    def graph_status(domain: str | None = None) -> dict:
        return tools.graph_status(domain)

    @server.tool(description="Entity types with instance counts and predicate usage for a domain's graph.")
    def list_entity_types(domain: str | None = None) -> dict:
        return tools.list_entity_types(domain)

    @server.tool(description="Find entities by name, label or IRI fragment; optionally restrict to an entity type.")
    def search_entities(query: str, domain: str | None = None, entity_type: str | None = None, limit: int = 10) -> list[dict]:
        return tools.search_entities(domain, query, entity_type, limit)

    @server.tool(description="Full description of one entity (by IRI or by name): attributes, relationships, neighbours.")
    def describe_entity(entity: str, domain: str | None = None, depth: int = 1) -> str:
        return tools.describe_entity(domain, entity, depth)

    @server.tool(description="An entity's context: source table, degree, linked datasets (with rows), the actions declared on "
                             "its class and its virtual attributes (values when compute_virtual_attributes=true).")
    def get_entity_context(entity: str, domain: str | None = None, compute_virtual_attributes: bool = False) -> dict:
        return tools.get_entity_context(domain, entity, compute_virtual_attributes)

    @server.tool(description="Compute an entity's virtual attributes live from the source (they are never stored in the graph).")
    def compute_virtual_attributes(entity: str, domain: str | None = None) -> dict:
        return tools.compute_virtual_attributes(domain, entity)

    @server.tool(description="Run one of the actions declared on the entity's class; the entity id is the only input.")
    def invoke_entity_action(entity: str, action: str, domain: str | None = None) -> dict:
        return tools.invoke_entity_action(domain, entity, action)

    @server.tool(description="The GraphQL schema (SDL) generated from the domain's ontology.")
    def get_graphql_schema(domain: str | None = None) -> str:
        return tools.get_graphql_schema(domain)

    @server.tool(description="Run a GraphQL query against the domain's graph; returns JSON.")
    def query_graphql(query: str, domain: str | None = None, variables: dict | None = None) -> str:
        return tools.query_graphql(domain, query, variables)

    return server
