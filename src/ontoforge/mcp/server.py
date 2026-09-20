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

    @server.tool(description="Describe a domain's ontology: classes, attributes and relationships, in plain text.")
    def describe_ontology(domain: str) -> str:
        return tools.describe_ontology(domain)

    @server.tool(description="Triple counts and entity types for a domain's graph.")
    def graph_status(domain: str) -> dict:
        return tools.graph_status(domain)

    @server.tool(description="Find entities by name, label or IRI fragment; optionally restrict to an entity type.")
    def search_entities(domain: str, query: str, entity_type: str | None = None, limit: int = 10) -> list[dict]:
        return tools.search_entities(domain, query, entity_type, limit)

    @server.tool(description="Full description of one entity (by IRI or by name): attributes, relationships, neighbours.")
    def describe_entity(domain: str, entity: str, depth: int = 1) -> str:
        return tools.describe_entity(domain, entity, depth)

    @server.tool(description="The GraphQL schema (SDL) generated from the domain's ontology.")
    def get_graphql_schema(domain: str) -> str:
        return tools.get_graphql_schema(domain)

    @server.tool(description="Run a GraphQL query against the domain's graph; returns JSON.")
    def query_graphql(domain: str, query: str, variables: dict | None = None) -> str:
        return tools.query_graphql(domain, query, variables)

    return server
