// The Ask assistant: matches a question to a glossary term, a domain or a screen and answers
// with links. Pure function over the data the screen already loaded, so it works offline and is testable.
import type { DomainSummary, GlossaryTerm, OntoClass, ClassMapping, SourceKind } from "@/api";

export interface AskLink { title: string; sub: string; icon: string; screen: string; domain?: string; params?: Record<string, string> }
export interface AskAnswer { text: string; links: AskLink[]; term?: GlossaryTerm & { domain: string; table: string } }

export interface AskContext { domain: string; domains: DomainSummary[]; glossary: GlossaryTerm[]; classes: OntoClass[]; mapping: Record<string, ClassMapping>; sourceKind: SourceKind }

export const SUGGESTIONS = ["What is net revenue?", "Where do I map Channel?", "How do I update the ontology from dim_customer?", "Which version is in review?", "Show hr domain", "Which DQ checks fail on fct_sales?"];

export function answer(q: string, ctx: AskContext): AskAnswer {
  const t = q.toLowerCase();
  const dom = ctx.domain;
  const D = ctx.domains.find(d => d.name === dom);
  const L = (title: string, sub: string, screen: string, params?: Record<string, string>, icon?: string): AskLink => ({ title, sub, icon: icon ?? screen, screen, domain: dom, params });
  const term = ctx.glossary.find(g => t.includes(g.term.toLowerCase())) || ctx.glossary.find(g => g.cols.some(c => t.includes(c.split(".")[1]))) || ctx.glossary.find(g => t.includes(g.cls.toLowerCase()) && /what|mean|defin|glossary/.test(t));
  const domHit = ctx.domains.find(d => t.includes(d.name) && d.name !== dom);
  if (domHit) {
    const d = domHit; const active = d.versions.find(v => v.active);
    return { text: `${d.name} · ${d.description}. ${d.versions.length ? `Active version v${active?.version ?? d.versions[0].version}, ${d.triples} triples, last build ${d.lastBuild}.` : "No version yet: create a draft to start."}`,
      links: [{ title: `Open ${d.name}`, sub: "Overview, versions, configuration", icon: "overview", screen: "overview", domain: d.name }, { title: "Configuration", sub: `${d.base_iri} · quorum ${d.quorum}`, icon: "settings", screen: "settings", domain: d.name }] };
  }
  if (term) {
    const table = term.cols[0].split(".")[0];
    return { text: `${term.term} is a glossary term in ${dom}, owned by ${term.steward}. It is modelled as the class ${term.cls} and sourced from ${term.cols.join(", ")}.`, term: { ...term, domain: dom, table },
      links: [L("Explore instances", `Search ${term.cls} entities in the graph`, "explore", { q: term.cls === "Customer" ? "Carrefour" : "" }), L("Data quality", `Constraints on ${term.cls}`, "quality")] };
  }
  if (/map|bind|column|table|unmapped/.test(t)) {
    const cls = ctx.classes.find(c => t.includes(c.id.toLowerCase()))?.id || "Channel";
    return { text: `Mapping binds a class to a table and its attributes to columns. ${cls} is currently ${ctx.mapping[cls]?.state || "unmapped"} in ${dom} v${D?.versions[0]?.version ?? "—"}. Open the designer, select ${cls}, then “Map to a table” or bind columns from the Data tab.`,
      links: [L(`Map ${cls}`, "Mapping designer · Status / Data / SQL", "mapping", { cls }), L("Browse catalog", "Find the source table in Metadata", "metadata")] };
  }
  if (/ontolog|class|attribute|relationship|update/.test(t)) return { text: "The ontology is edited in draft versions only. Use Metadata → Ontology to push new columns into a class, or edit classes directly on the map. Checks run on save.", links: [L("Ontology map", `${ctx.classes.length} classes · edit in the side panel`, "ontology"), L("Update from a table", "Compare dim_customer with Customer", "metadata", { table: "dim_customer", tab: "onto" })] };
  if (/build|graph|triple/.test(t)) return { text: `A build compiles the mapping to ${ctx.sourceKind === "postgres" ? "Postgres" : "Databricks"} SQL, loads triples, infers, runs rules and quality, then publishes. The last ${dom} build succeeded 2 h ago with 263,695 triples.`, links: [L("Build", "Start a build, watch steps, history", "build"), L("Triples", "Paged grid with filters", "triples")] };
  if (/qualit|dq|violation|check/.test(t)) return { text: `Data quality runs 7 constraints on ${dom}. Open issues: 12 on Sale.quantity (min_exclusive), 3 on Customer.country (pattern), 312 unlabelled entities.`, links: [L("Data quality", "Constraints and results", "quality"), L("Quick DQ on fct_sales", "Profile and column checks", "metadata", { table: "fct_sales", tab: "dq" })] };
  if (/explore|find|who|which|customer|sale|product/.test(t)) return { text: `Explore searches entities by label or IRI and opens them with their attributes and relationships. Try “Carrefour” in ${dom}.`, links: [L("Explore", "Search, entity drawer, expand", "explore", { q: "Carrefour" }), L("Analytics", "Hubs and communities", "analytics")] };
  if (/review|approve|publish|lease|version|compare/.test(t)) {
    const vs = D?.versions ?? []; const dr = vs.find(v => v.status === "draft"), ir = vs.find(v => v.status === "in_review"), ac = vs.find(v => v.active);
    return { text: `Versions move draft → in review → published → archived. In ${dom}: ${dr ? `v${dr.version} is a draft${dr.lease ? ` (lease ${dr.lease.holder}, ${dr.lease.expires} left)` : ""}` : "no draft"}${ir ? `, v${ir.version} is in review with ${ir.review?.approved ?? 0} of ${ir.review?.quorum ?? D?.quorum} approvals` : ""}${ac ? `, v${ac.version} is active` : ""}.`, links: [L("Versions", "Timeline, compare, lifecycle actions", "versions"), { title: "My tasks", sub: "Reviews waiting for you", icon: "tasks", screen: "tasks" }] };
  }
  return { text: "I could not match that to a term or a screen. Try a glossary term (“net revenue”), a task (“map Channel”), or a domain name (“hr”).", links: [L(`Open ${dom}`, "Overview, versions, configuration", "overview"), L("Glossary", "Search terms in Metadata", "metadata", { tab: "glossary" })] };
}
