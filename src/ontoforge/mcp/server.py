"""MCP server exposing GraphTools. Run over stdio with ``python -m ontoforge serve-mcp``."""
from __future__ import annotations

import functools

from mcp.server.mcpserver import MCPServer

from .tools import GraphTools

INSTRUCTIONS = (
    "You are connected to a datagraph knowledge-graph server. Start with list_domains, then describe_ontology "
    "for the domain you need. Read the graph with search_entities / describe_entity, class_schema, ontology_paths "
    "and graph_aggregate, or get_graphql_schema + query_graphql for structured, nested questions. The whole "
    "backend is here too: design the draft (add_class, map_class, add_attribute, add_relationship, exclude_property), "
    "snapshot tables (import_tables), profile and check data quality, keep the glossary, add reasoning rules and "
    "constraints, build (start_build, incremental), and move versions through review and publication. Every action "
    "runs as the signed-in caller under the domain's lease, role and MCP policy."
)


def create_mcp_server(tools: GraphTools, name: str = "ontoforge") -> MCPServer:
    server = MCPServer(name, instructions=INSTRUCTIONS, version="0.1.0")

    def tool(description: str):
        """server.tool, plus the domain's MCP policy: a tool the domain disabled answers with an error, whatever it is."""
        def register(fn):
            @functools.wraps(fn)
            def run(*args, **kwargs):
                if msg := tools._disabled(fn.__name__, kwargs.get("domain")):
                    ret = fn.__annotations__.get("return")
                    return msg if ret is str else [{"error": msg}] if ret is list or str(ret).startswith("list") else {"error": msg}
                return fn(*args, **kwargs)
            return server.tool(description=description)(run)
        return register

    @tool(description="List knowledge-graph domains with their served version and triple count.")
    def list_domains() -> list[dict]:
        return tools.list_domains()

    @tool(description="Select the domain that later tools use when 'domain' is omitted.")
    def select_domain(domain: str) -> dict:
        return tools.select_domain(domain)

    @tool(description="Versions of a domain with status, content flags and build state.")
    def list_domain_versions(domain: str | None = None) -> list[dict]:
        return tools.list_domain_versions(domain)

    @tool(description="Design readiness of a domain: ontology, mapping completion, build, drift.")
    def get_design_status(domain: str | None = None) -> dict:
        return tools.get_design_status(domain)

    @tool(description="Describe a domain's ontology: classes, attributes and relationships, in plain text.")
    def describe_ontology(domain: str | None = None) -> str:
        return tools.describe_ontology(domain)

    @tool(description="Triple counts and entity types for a domain's graph.")
    def graph_status(domain: str | None = None) -> dict:
        return tools.graph_status(domain)

    @tool(description="Entity types with instance counts and predicate usage for a domain's graph.")
    def list_entity_types(domain: str | None = None) -> dict:
        return tools.list_entity_types(domain)

    @tool(description="Find entities by name, label or IRI fragment; optionally restrict to an entity type.")
    def search_entities(query: str, domain: str | None = None, entity_type: str | None = None, limit: int = 10) -> list[dict]:
        return tools.search_entities(domain, query, entity_type, limit)

    @tool(description="Full description of one entity (by IRI or by name): attributes, relationships, neighbours.")
    def describe_entity(entity: str, domain: str | None = None, depth: int = 1) -> str:
        return tools.describe_entity(domain, entity, depth)

    @tool(description="An entity's context: source table, degree, linked datasets (with rows), the actions declared on "
                             "its class and its virtual attributes (values when compute_virtual_attributes=true).")
    def get_entity_context(entity: str, domain: str | None = None, compute_virtual_attributes: bool = False) -> dict:
        return tools.get_entity_context(domain, entity, compute_virtual_attributes)

    @tool(description="Compute an entity's virtual attributes live from the source (they are never stored in the graph).")
    def compute_virtual_attributes(entity: str, domain: str | None = None) -> dict:
        return tools.compute_virtual_attributes(domain, entity)

    @tool(description="Run one of the actions declared on the entity's class; the entity id is the only input.")
    def invoke_entity_action(entity: str, action: str, domain: str | None = None) -> dict:
        return tools.invoke_entity_action(domain, entity, action)

    @tool(description="The GraphQL schema (SDL) generated from the domain's ontology.")
    def get_graphql_schema(domain: str | None = None) -> str:
        return tools.get_graphql_schema(domain)

    @tool(description="Run a GraphQL query against the domain's graph; returns JSON.")
    def query_graphql(query: str, domain: str | None = None, variables: dict | None = None) -> str:
        return tools.query_graphql(domain, query, variables)

    @tool(description="What a class holds and how it connects: attributes (measures, dates), outgoing and incoming relationships with their IRIs. Use before graph_aggregate.")
    def class_schema(cls: str, domain: str | None = None) -> dict:
        return tools.class_schema(domain, cls)

    @tool(description="How to get from one class to another through the relationships (shortest paths, forward or inverse steps), for filters and group_by paths in graph_aggregate.")
    def ontology_paths(from_cls: str, to_cls: str, domain: str | None = None, max_depth: int = 6) -> dict:
        return tools.ontology_paths(domain, from_cls, to_cls, max_depth)

    @tool(description="Count the instances of a class in the graph and sum/avg/min/max a numeric attribute, grouped by ONE dimension: an attribute (group_kind 'value', or 'year' / 'month' of a date) or a relationship target, reached directly or through a path of steps (a list means a chain, e.g. ['inTerritory', 'territoryGroup'], never two dimensions). filters keep instances that reach a value through a path (a step is a property name or IRI, '^' + name walks it backwards). Over time: group_by the date attribute with group_kind 'year'; against peers: group_by the relationship; both: filter on one, group by the other.")
    def graph_aggregate(cls: str, measure: str | None = None, group_by: str | list[str] | None = None, group_kind: str = "value", filters: list[dict] | None = None, limit: int = 50, domain: str | None = None) -> dict:
        return tools.graph_aggregate(domain, cls, measure, group_by, group_kind, filters, limit)

    @tool(description="Tables in the domain's snapshot (the ones every table tool accepts), with column count, key, whether profiled, and how many rules each has. Call this before naming a table.")
    def list_tables(domain: str | None = None) -> list[dict]:
        return tools.list_tables(domain)

    @tool(description="Profile of a table in the domain's working version: rows, missing cells, row key, per-column nulls, distinct values, ranges, top values, hints. Call run_profile first if there is none.")
    def table_profile(table: str, domain: str | None = None) -> dict:
        return tools.table_profile(domain, table)

    @tool(description="Profile a table now (reads the source; seconds to minutes). Returns the headline numbers.")
    def run_profile(table: str, domain: str | None = None) -> dict:
        return tools.run_profile(domain, table)

    @tool(description="Data quality of a table: score, rules with their last pass rate and status, columns scoring under 95%.")
    def table_quality(table: str, domain: str | None = None) -> dict:
        return tools.table_quality(domain, table)

    @tool(description="Run every enabled data-quality rule of a table against the source now and return the new scores.")
    def run_quality_rules(table: str, domain: str | None = None) -> dict:
        return tools.run_quality_rules(domain, table)

    @tool(description="Add a data-quality rule. kind: not_null | unique | in_set {values} | range {min,max} | regex {pattern} | referential {ref_table, ref_column} | freshness {hours} | row_count {min,max} | custom {predicate}. threshold is the pass fraction that counts as passing.")
    def add_quality_rule(table: str, name: str, kind: str, column: str | None = None, params: dict | None = None, threshold: float = 0.95, domain: str | None = None) -> dict:
        return tools.add_quality_rule(domain, table, name, kind, column, params, threshold)

    @tool(description="Derive data-quality rules from the table's profile (keys, never-null columns, code sets, numeric ranges, row-count band); no AI involved.")
    def suggest_quality_rules(table: str, domain: str | None = None) -> dict:
        return tools.suggest_quality_rules(domain, table)

    @tool(description="A sample of the source rows that break a row-level data-quality rule (by rule id from table_quality).")
    def failing_rows(rule_id: str, limit: int = 10) -> dict:
        return tools.failing_rows(rule_id, limit)

    @tool(description="Business terms and KPI metrics of the domain's glossary, optionally for one table or matching a search text.")
    def glossary(domain: str | None = None, table: str | None = None, q: str | None = None) -> list[dict]:
        return tools.glossary(domain, table, q)

    @tool(description="Recent builds of the domain's working version: status, duration, triples, the plan (which tables were read).")
    def list_builds(domain: str | None = None, limit: int = 5) -> list[dict]:
        return tools.list_builds(domain, limit)

    @tool(description="Start a build of the domain's working version (incremental unless full=true). Returns the run to watch with list_builds.")
    def start_build(domain: str | None = None, full: bool = False) -> dict:
        return tools.start_build(domain, full)

    @tool(description="Add a class to the ontology of the domain's working draft (optionally under a parent). Then map_class ties it to a table.")
    def add_class(name: str, label: str | None = None, description: str | None = None, parent: str | None = None, domain: str | None = None) -> dict:
        return tools.add_class(domain, name, label, description, parent)

    @tool(description="Add a relationship from one class to another in the ontology, and map it when its key is given: fk_column names the foreign-key column, sitting on the source class's table (fk_on 'from', the default) or on the target class's table (fk_on 'to'); or link_table with source_key and target_key when a separate table joins the two. A build then loads it.")
    def add_relationship(name: str, from_cls: str, to_cls: str, label: str | None = None, description: str | None = None, fk_column: str | None = None, fk_on: str = "from",
                         link_table: str | None = None, source_key: list[str] | None = None, target_key: list[str] | None = None, domain: str | None = None) -> dict:
        return tools.add_relationship(domain, name, from_cls, to_cls, label, description, fk_column, fk_on, link_table, source_key, target_key)

    @tool(description="Map an existing relationship onto the rows: fk_column on the source's table (fk_on 'from') or on the target's table (fk_on 'to'), or link_table + source_key + target_key. Both classes must be mapped first.")
    def map_relationship(relationship: str, fk_column: str | None = None, fk_on: str = "from", link_table: str | None = None, source_key: list[str] | None = None,
                         target_key: list[str] | None = None, domain: str | None = None) -> dict:
        return tools.map_relationship(domain, relationship, fk_column, fk_on, link_table, source_key, target_key)

    @tool(description="Add an attribute (datatype property) to a class and, with column, bind it to that column of the class's table. datatype: string | integer | decimal | double | boolean | date | dateTime.")
    def add_attribute(cls: str, name: str, column: str | None = None, datatype: str | None = None, label: str | None = None, description: str | None = None, domain: str | None = None) -> dict:
        return tools.add_attribute(domain, cls, name, column, datatype, label, description)

    @tool(description="Map a class onto a table of the domain's snapshot: each row is one instance identified by key_columns. Keeps the attribute bindings when the table is unchanged.")
    def map_class(cls: str, table: str, key_columns: list[str], domain: str | None = None) -> dict:
        return tools.map_class(domain, cls, table, key_columns)

    @tool(description="Remove a relationship from the ontology and its mapping. A build then drops its triples.")
    def remove_relationship(relationship: str, domain: str | None = None) -> dict:
        return tools.remove_relationship(domain, relationship)

    @tool(description="Add a glossary term (kind 'term') or KPI metric (kind 'metric') to the domain: definition, the table and columns it rests on, the class it names, and for a metric its formula, unit and frequency. status: draft | pending | approved | certified.")
    def add_term(kind: str, name: str, definition: str = "", table: str | None = None, columns: list[str] | None = None, class_name: str | None = None,
                 formula: str | None = None, unit: str | None = None, frequency: str | None = None, status: str = "draft", owner: str | None = None, domain: str | None = None) -> dict:
        return tools.add_term(domain, kind, name, definition, table, columns, class_name, formula, unit, frequency, status, owner)

    @tool(description="Change a glossary term or metric (by id from glossary): any of name, definition, status, table, columns, class_name, formula, unit, frequency, owner.")
    def update_term(term_id: str, name: str | None = None, definition: str | None = None, status: str | None = None, table: str | None = None, columns: list[str] | None = None,
                    class_name: str | None = None, formula: str | None = None, unit: str | None = None, frequency: str | None = None, owner: str | None = None) -> dict:
        return tools.update_term(term_id, name, definition, status, table, columns, class_name, formula, unit, frequency, owner)

    @tool(description="Delete a glossary term or metric by id.")
    def delete_term(term_id: str) -> dict:
        return tools.delete_term(term_id)

    @tool(description="Create the next draft version of a domain (copies the latest version's design). Fails while a draft exists.")
    def create_version(domain: str | None = None) -> dict:
        return tools.create_version(domain)

    @tool(description="Move a version along the lifecycle. to: in_review (from draft; builder) | draft or published (from in_review; reviewer, publishing needs the review quorum) | archived (from published; admin). version defaults to the working one.")
    def transition_version(to: str, version: int | None = None, domain: str | None = None) -> dict:
        return tools.transition_version(domain, to, version)

    @tool(description="Record a review (approve or reject, with a comment) on a version in review; reviewer role.")
    def review_version(approved: bool, comment: str | None = None, version: int | None = None, domain: str | None = None) -> dict:
        return tools.review_version(domain, approved, comment, version)

    @tool(description="Leave a comment on a version.")
    def comment_version(body: str, version: int | None = None, domain: str | None = None) -> dict:
        return tools.comment_version(domain, body, version)

    @tool(description="Serve a published version of the domain (its graph answers the graph tools); version None serves nothing. Reviewer role.")
    def set_active_version(version: int | None, domain: str | None = None) -> dict:
        return tools.set_active_version(domain, version)

    @tool(description="Delete a version of the domain by number (its graph and design go with it).")
    def delete_version(version: int, domain: str | None = None) -> dict:
        return tools.delete_version(domain, version)

    @tool(description="Create a domain with its base IRI (e.g. http://example.com/sales/) and a first draft. Its source connection is chosen in Settings.")
    def create_domain(name: str, base_iri: str, description: str | None = None, review_quorum: int = 1) -> dict:
        return tools.create_domain(name, base_iri, description, review_quorum)

    @tool(description="Change a domain's settings: description, base_iri, review_quorum, materialization (none | view | table), target_schema.")
    def update_domain(description: str | None = None, base_iri: str | None = None, review_quorum: int | None = None, materialization: str | None = None,
                      target_schema: str | None = None, domain: str | None = None) -> dict:
        return tools.update_domain(domain, description, base_iri, review_quorum, materialization, target_schema)

    @tool(description="Set the domain's MCP policy: whether it is exposed to agents and which tools are disabled for it.")
    def set_mcp_policy(disabled_tools: list[str] | None = None, exposed: bool = True, domain: str | None = None) -> dict:
        return tools.set_mcp_policy(domain, disabled_tools, exposed)

    @tool(description="Delete a domain and everything in it. Admin role.")
    def delete_domain(domain: str | None = None) -> dict:
        return tools.delete_domain(domain)

    @tool(description="Snapshot tables of the domain's source into its working version (columns, keys), so they can be mapped and profiled. Names as the source spells them, optionally with schema.")
    def import_tables(tables: list[str], schema: str | None = None, domain: str | None = None) -> list[dict]:
        return tools.import_tables(domain, tables, schema)

    @tool(description="Re-read every snapshotted table from the source and report what changed (columns added, dropped, retyped).")
    def refresh_metadata(domain: str | None = None) -> dict:
        return tools.refresh_metadata(domain)

    @tool(description="Describe a snapshotted table, or one of its columns when column is given (comment None clears it).")
    def set_table_comment(table: str, comment: str | None, column: str | None = None, domain: str | None = None) -> dict:
        return tools.set_table_comment(domain, table, comment, column)

    @tool(description="Drop a table from the working version's snapshot.")
    def remove_table(table: str, domain: str | None = None) -> dict:
        return tools.remove_table(domain, table)

    @tool(description="Mark a class's attribute or relationship as deliberately unmapped (it stops counting against mapping completion); excluded=false takes it back.")
    def exclude_property(cls: str, prop: str, excluded: bool = True, domain: str | None = None) -> dict:
        return tools.exclude_property(domain, cls, prop, excluded)

    @tool(description="Drop a class's mapping and every relation touching it; the ontology keeps the class.")
    def unmap_class(cls: str, domain: str | None = None) -> dict:
        return tools.unmap_class(domain, cls)

    @tool(description="The reasoning rules of the working version: name, text, mode, enabled.")
    def list_rules(domain: str | None = None) -> list[dict]:
        return tools.list_rules(domain)

    @tool(description="Add or replace a reasoning rule in SWRL-style text over the ontology's names, e.g. 'Employee(?e) ^ salary(?e, ?s) ^ swrlb:greaterThan(?s, 1000) -> HighEarner(?e)'. mode: materialize (adds triples at build) | violation (reports matches).")
    def add_rule(name: str, text: str, mode: str = "materialize", enabled: bool = True, domain: str | None = None) -> dict:
        return tools.add_rule(domain, name, text, mode, enabled)

    @tool(description="Remove a reasoning rule by name.")
    def remove_rule(name: str, domain: str | None = None) -> dict:
        return tools.remove_rule(domain, name)

    @tool(description="The graph constraints (SHACL-like) of the working version.")
    def list_constraints(domain: str | None = None) -> list[dict]:
        return tools.list_constraints(domain)

    @tool(description="Add or replace a graph constraint on a class, optionally on one property. kind: min_count | max_count | datatype | class | pattern | in | min_inclusive | max_inclusive | min_exclusive | max_exclusive | unique | node_kind | require_label | no_orphans. severity: violation | warning | info.")
    def add_constraint(name: str, target_class: str, kind: str, property: str | None = None, value=None, severity: str = "violation", message: str | None = None, domain: str | None = None) -> dict:
        return tools.add_constraint(domain, name, target_class, kind, property, value, severity, message)

    @tool(description="Remove a graph constraint by name.")
    def remove_constraint(name: str, domain: str | None = None) -> dict:
        return tools.remove_constraint(domain, name)

    @tool(description="Run one read-only SELECT against the domain's source warehouse and return up to `limit` rows. Table names as the mapping spells them.")
    def preview_sql(sql: str, domain: str | None = None, limit: int = 20) -> dict:
        return tools.preview_sql(domain, sql, limit)

    return server
