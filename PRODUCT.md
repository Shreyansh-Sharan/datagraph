# ontoforge

**What it is:** a semantic-layer / knowledge-graph backend and UI. A builder designs an ontology, maps it onto warehouse tables, builds a graph inside Postgres from the warehouse (Databricks first), reasons over it, and exposes it to people (Explore) and LLM agents (MCP, GraphQL).

**Register:** product (design serves the task). Users are data engineers, analytics leads and domain experts at Polestar Analytics and its clients, working at a desk in an IDE-and-dashboards day: long sessions, dense information, keyboard-heavy, light or dark rooms. Trust comes from familiarity with Linear / Databricks / Notion-class tools, not novelty.

**Primary jobs:**
1. Draft and refine an ontology from tables (with AI help), map it, build the graph, publish a version.
2. Explore the graph: find an entity, see what it connects to, follow relationships, spot structure (communities, hubs).
3. Govern: review, approve, publish, pin the served version, control what MCP exposes.

**Non-goals:** marketing surface; mobile-first (tablet-tolerant is enough); custom visual language for standard controls.

**Voice:** plain, specific, terse. Button labels say what happens. No buzzwords.
