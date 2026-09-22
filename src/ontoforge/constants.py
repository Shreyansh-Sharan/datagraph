"""Cross-package constants that must not create import cycles."""

# Every tool the MCP server can expose; per-domain policy may disable any domain-scoped one.
MCP_TOOLS = ("list_domains", "select_domain", "list_domain_versions", "get_design_status", "describe_ontology",
             "graph_status", "list_entity_types", "search_entities", "describe_entity", "get_entity_context",
             "compute_virtual_attributes", "invoke_entity_action", "get_graphql_schema", "query_graphql")
MCP_REGISTRY_TOOLS = ("list_domains", "select_domain", "list_domain_versions", "get_design_status")
# The rest of the catalogue: every tool a domain's MCP policy may disable (all take a domain).
MCP_DOMAIN_TOOLS = MCP_TOOLS[4:] + (
    "class_schema", "ontology_paths", "graph_aggregate", "list_tables", "table_profile", "run_profile", "table_quality", "run_quality_rules",
    "add_quality_rule", "suggest_quality_rules", "failing_rows", "quality_rule_kinds", "quality_overview", "glossary", "list_builds", "start_build", "preview_sql",
    "add_class", "add_relationship", "map_relationship", "add_attribute", "map_class", "remove_relationship",
    "add_term", "update_term", "delete_term", "create_version", "transition_version", "review_version", "comment_version", "set_active_version",
    "delete_version", "update_domain", "set_mcp_policy", "delete_domain", "import_tables", "refresh_metadata", "set_table_comment", "remove_table",
    "exclude_property", "unmap_class", "list_rules", "add_rule", "remove_rule", "list_constraints", "add_constraint", "remove_constraint")
