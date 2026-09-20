"""Cross-package constants that must not create import cycles."""

# Every tool the MCP server can expose; per-domain policy may disable any domain-scoped one.
MCP_TOOLS = ("list_domains", "select_domain", "list_domain_versions", "get_design_status", "describe_ontology",
             "graph_status", "list_entity_types", "search_entities", "describe_entity", "get_entity_context",
             "get_graphql_schema", "query_graphql")
MCP_REGISTRY_TOOLS = ("list_domains", "select_domain", "list_domain_versions", "get_design_status")
