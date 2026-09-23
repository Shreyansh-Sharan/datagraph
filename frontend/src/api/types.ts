// Shared UI model. The mock adapter produces these directly; the REST adapter maps
// backend JSON (see docs/UI-BLUEPRINT.html §8) onto the same shapes.

export type SourceKind = "databricks" | "postgres";
export type Role = "viewer" | "builder" | "reviewer" | "admin";
export type VersionStatus = "draft" | "in_review" | "published" | "archived";
export type MappingState = "complete" | "partial" | "unmapped";

export const ROLE_RANK: Record<Role, number> = { viewer: 0, builder: 1, reviewer: 2, admin: 3 };

export interface Config {
  sourceKind: SourceKind;
  catalog: string | null;      // deployment default catalog (Databricks) or null
  authMode: "header" | "token";
  authHeader: string;
  materialization: string;     // "none" | "view" | "table" (+ clustering notes)
  capabilities: { profiling: boolean; quality: boolean; glossary: boolean };   // what this deployment offers beyond the core; screens hide the rest
}

export interface Me { name: string; role: Role }

export interface VersionStats { classes: number; attrs: number; rels: number; bindings: number; rules: number; constraints: number; triples: number }
export interface ReviewRow { who: string; note: string; state: "approved" | "pending" | "rejected"; when?: string }
export interface Review { approved: number; quorum: number; rows: ReviewRow[]; rejected?: number; round?: number }
export interface Lease { holder: string; expires: string; expiresAt?: string | null; expired?: boolean }

export interface VersionInfo {
  id?: string;                  // backend uuid when known
  version: number;
  status: VersionStatus;
  content: string;              // "ontology · mapping 78% · 2 rules · 7 constraints"
  mappingPct: number | null;
  lastBuild: string;            // "succeeded · 2 h ago"
  active: boolean;
  created: string;
  by: string;
  stats: VersionStats;
  lease?: Lease | null;
  review?: Review | null;
  changes: { sign: "+" | "-" | "~"; text: string }[];
}

export interface DomainSource { connectionId: string | null; catalog: string | null; schemas: string[] }   // null connection: the deployment's env source
export interface SourceInput { connection_id: string | null; catalog: string | null; schemas: string[] }

export interface DomainSummary {
  name: string;
  description: string;
  base_iri: string;
  quorum: number;
  schema: string;               // the default schema (first of `schemas`), for the catalog browser
  schemas: string[];            // the primary source's schemas, in priority order
  sources: DomainSource[];      // every source the domain reads; the first is the primary
  catalog: string;              // domain catalog (Databricks) or schema prefix (Postgres)
  materialization: string;
  target: string;               // warehouse publish target
  mcpExposed: boolean;
  disabledTools: string[];
  triples: string;
  lastBuild: string;
  versions: VersionInfo[];
  lease: Lease | null;
  review: Review | null;
  connectionId?: string | null;
  aiConnectionId?: string | null;
  targetSchema?: string | null;
}

export interface AuditEntry { who: string; what: string; version: number; when: string }
export interface Comment { who: string; when: string; text: string }

// -- catalog / metadata ----------------------------------------------------------
export interface CatalogTable { name: string; cols: number; imported: boolean; cls: string | null; held?: string | null }   // held: the snapshot's own name for the table, when imported
export interface SnapshotTable { table: string; columns: number; columnNames: string[]; comment: string | null; primaryKey: string[]; capturedAt?: string | null }   // one table in a version's metadata snapshot
export interface RefreshChange { table: string; missing: boolean; added: string[]; removed: string[]; modified: { column: string; from: string; to: string }[]; keys_changed: boolean }
export interface CatalogColumn { name: string; type: string; comment: string; key: "pk" | "fk" | null; keyInferred: boolean }
export interface TableDetail { name: string; fullName: string; comment: string; columns: CatalogColumn[] }
// -- table insights: profile, data quality, glossary ----------------------------------------------
export type ColumnRole = "row key" | "binary" | "feature";
export type ColumnKind = "numeric id" | "numeric" | "categorical" | "boolean" | "date";
export interface ColumnProfile {
  name: string; type: string; nulls: number; null_rate: number; distinct: number | null; min: string | null; max: string | null; top: string | null; top_share: number | null;
  role: ColumnRole; kind: ColumnKind; non_null: number; unique_pct: number | null; balance: number | null;
  mean: number | null; mean_ci: number | null; std: number | null; median: number | null; q1: number | null; q3: number | null;
  skew: number | null; kurtosis: number | null; normal_p: number | null; outliers: number | null; outlier_rate: number | null; zeros_rate: number | null; heaped_rate: number | null; peaks: number | null;
  histogram: { lo: number; hi: number; n: number }[]; values: { value: string; n: number }[]; hints: string[];
}
export interface TableProfile { table: string; profiled_at: string; actor: string | null; sample_pct: number; row_count: number | null; size_bytes: number | null; last_modified: string | null; duplicate_keys: number | null; columns: ColumnProfile[]; duplicate_rows: number | null; missing_cells: number | null; row_key: string[] }
export type DqKind = "not_null" | "not_empty" | "unique" | "in_set" | "not_in_set" | "range" | "not_in_range" | "equal_to" | "not_equal_to" | "not_less_than" | "not_greater_than"
  | "regex" | "valid_email" | "valid_uuid" | "valid_ipv4" | "valid_date" | "valid_timestamp" | "string_case" | "length_between" | "not_in_future" | "older_than_days" | "older_than_column"
  | "referential" | "freshness" | "row_count" | "aggregate" | "custom";
export interface DqParam { name: string; type: string; required: boolean; help: string }   // type: number | list | scalar | regex | sql | column | table | enum:a,b
export interface DqKindInfo { kind: DqKind; label: string; dimension: string; level: "row" | "table"; column: boolean; dqx: string; params: DqParam[]; help: string }
export interface DqTableSummary { table: string; rules: number; enabled: number; kinds: Record<string, number>; dimensions: Record<string, number>; summary: { passing: number; warning: number; failing: number; error: number }; score: number | null; last_run_at: string | null; last_run_status: string | null }
export interface DqOverview { tables: DqTableSummary[]; rules: DqRule[]; kinds: DqKindInfo[] }
export type DqRuleStatus = "passing" | "warning" | "failing" | "error";
export interface DqResult { pass_rate: number | null; passed: number | null; failed: number | null; total: number | null; status: DqRuleStatus; error: string | null; ran_at: string }
export interface DqRule { id: string; table_name: string; name: string; column_name: string | null; kind: DqKind; dimension: string; params: Record<string, unknown>; threshold: number; owner: string | null; origin: "manual" | "ai" | "auto"; enabled: boolean; last: DqResult | null; history: { pass_rate: number | null; ran_at: string }[] }
export type Cell = string | number | boolean | null;
export interface FailingRows { columns: string[]; rows: Cell[][] }
export interface DqRun { id: string; started_at: string; finished_at: string | null; score: number | null; status: string; error: string | null }
export interface DqStatus { table: string; score: number | null; last_run: DqRun | null; history: { id: string; started_at: string; score: number | null; status: string }[]; rules: DqRule[]; columns: { name: string; score: number | null; source: "rules" | "profile" | null }[]; summary: { passing: number; warning: number; failing: number } }
export interface RuleInput { name: string; kind: DqKind; column?: string | null; params?: Record<string, unknown>; dimension?: string | null; threshold?: number; owner?: string | null; enabled?: boolean }
export type GlossaryStatus = "draft" | "pending" | "approved" | "certified";
export interface GlossaryEntry { id: string; kind: "term" | "metric"; name: string; definition: string; status: GlossaryStatus; schema_name: string | null; table_name: string | null; columns: string[]; class_name: string | null; formula: string | null; unit: string | null; frequency: string | null; owner: string | null; updated_at: string; updated_by: string | null }
export interface TermInput { kind: "term" | "metric"; name: string; definition?: string; table?: string | null; columns?: string[]; status?: GlossaryStatus; owner?: string | null; class_name?: string | null; formula?: string | null; unit?: string | null; frequency?: string | null }
// -- the assistant --------------------------------------------------------------------------------
export interface AssistantContext { domain?: string; version?: number; screen?: string; table?: string; cls?: string; entity?: string }
export interface ToolTrace { id: string; name: string; arguments: Record<string, unknown>; result: string }
export type ChatEvent =
  | { type: "tool_call"; id: string; name: string; arguments: Record<string, unknown> }
  | { type: "tool_result"; id: string; name: string; result: string }
  | { type: "text"; text: string }
  | { type: "done"; conversation_id: string; answer: string; tools: ToolTrace[] }
  | { type: "error"; error: string };
export interface ChatResult { conversation_id: string; answer: string; tools: ToolTrace[] }
export interface Conversation { id: string; domain: string | null; title: string; context: AssistantContext; created_at: string; updated_at: string }
export interface ChatMessage { id: number; role: "user" | "assistant" | "tool"; content: string | null; tool_calls: { id: string; name: string; arguments: Record<string, unknown> }[] | null; tool_call_id: string | null; name: string | null; created_at: string }
/** The Ask assistant's view of a glossary entry. */
export interface GlossaryTerm { term: string; def: string; cls: string; cols: string[]; steward: string }
export const askTerm = (e: GlossaryEntry): GlossaryTerm => ({ term: e.name, def: e.definition, cls: e.class_name ?? "", cols: e.columns.map(c => `${(e.table_name ?? "").split(".").pop() ?? ""}.${c}`), steward: e.owner ?? "" });

// -- ontology ------------------------------------------------------------------------
export interface OntoClass { id: string; iri: string; x: number; y: number; desc: string; parents: string[]; attrs: { name: string; range: string }[]; rels: { name: string; target: string }[] }
export interface OntoCheck { severity: "error" | "warning" | "info"; code: string; subject: string; message: string; target: { screen: "ontology" | "mapping"; cls: string } }

// -- mapping --------------------------------------------------------------------------
export interface ClassMapping { table?: [string, string]; fullName?: string; sql?: string; key: string; state: MappingState; cols: Record<string, string>; rels?: Record<string, string>; excluded?: string[] }
export interface AiProgress { progress: string; startedAt: string | null; progressAt: string | null; status: "running" | "succeeded" | "failed" }   // what a long AI task is doing right now
export interface DriftIssue { kind: string; table: string; column: string | null; detail: string; mapping_ref: string; severity: string }
export interface MappingKpis { completion: number; classesMapped: [number, number]; attributes: [number, number]; relationships: [number, number]; excluded: number }
export interface TablePreview { columns: string[]; rows: (string | null)[][] }

// -- rules / quality -------------------------------------------------------------------
export interface Rule { name: string; mode: "materialize" | "violation"; text: string; enabled: boolean; lastRun: string }
export interface Constraint { name: string; target: string; kind: string; severity: "violation" | "warning" | "info"; count: number; sample: string; sampleEntity?: string }

// -- build ------------------------------------------------------------------------------
export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export interface BuildStep { name: string; detail: string; seconds: number | null; state: "done" | "running" | "queued" }
export interface BuildRun { id: string; label?: string; status: RunStatus; actor: string; duration: string; triples: string; inferred: string; error: string; steps: BuildStep[]; stepIndex: number }   // id is what the API polls; label is what the screen shows
export interface ChecklistItem { label: string; value: string; ok: boolean; go: { screen: string; arg?: string } }

// -- graph ------------------------------------------------------------------------------
export interface SearchHit { id: string; label: string; type: string }
export interface EntityDetail {
  id: string; label: string; type: string; iri: string;
  attrs: { k: string; v: string; dt: string; inferred: boolean }[];
  out: { pred: string; targets: SearchHit[] }[];
  inc: { pred: string; count: string; targets: SearchHit[] }[];
  far: { pred: string; target: SearchHit }[]; // depth-2 neighbours
}
export interface GraphStatus { triples: string; inferred: string; entities: string; types: { name: string; iri: string; count: number }[] }
export interface GraphSample { nodes: { id: string; label: string; type: string }[]; edges: { from: string; to: string; label: string }[] }
export type SearchMatch = "contains" | "exact" | "starts_with";
export interface SearchOptions { type?: string | null; match?: SearchMatch }   // type: a class IRI from GraphStatus.types
export interface TripleRow { s: string; p: string; o: string; isIri: boolean; dt: string; inferred: boolean }
export interface TripleQuery { q: string; filter: "all" | "asserted" | "inferred"; sort: "subject" | "predicate" | "object" | "inferred"; dir: "asc" | "desc"; limit: number; offset: number }
export interface TriplePage { total: string; rows: TripleRow[] }

// -- analytics ----------------------------------------------------------------------------
export interface Analytics {
  health: { label: string; value: string; sub: string; tone: "blue" | "ink" | "warn" }[];
  perClass: { label: string; n: number; color: string }[];
  runs: { kind: string; params: string; result: string; when: string }[];
  top: { label: string; type: string; score: string; entity: string }[];
}

// -- settings / admin --------------------------------------------------------------------
export interface ConnResult { ok: boolean; title: string; detail: string; action?: string | null; latency_ms?: number; at?: string }

// -- connections (Configure screen) -----------------------------------------------------
export type ConnectorKind = "postgres" | "databricks" | "sqlserver" | "azure_openai" | (string & {});   // hub deployments add their own kinds
export interface ConnectorField { name: string; label: string; kind: "text" | "password" | "number" | "select"; required: boolean; default: string | number | null; options: string[]; help: string | null; option_titles?: Record<string, string> | null; show_when?: Record<string, string | number | boolean> | null }
export interface ConnectorSpec { kind: ConnectorKind; label: string; category: "source" | "ai"; secret_field: string; docs: string | null; fields: ConnectorField[]; source?: "local" | "hub" }
export interface ConnectionRec { id: string; name: string; kind: ConnectorKind; config: Record<string, string | number>; has_secret: boolean; last_test: ConnResult | null; created_by: string | null; created_at: string; updated_at: string; source?: "local" | "hub" }
export interface SourceFactsEntry { kind: string; connection: string | null; connection_id: string | null; catalog: string | null; schemas: string[]; host: string | null; last_test: ConnResult | null; missing_connection_id?: string | null }
export interface SourceFacts { kind: string; connection: string | null; connection_id: string | null; catalog: string | null; schema: string | null; schemas?: string[]; sources?: SourceFactsEntry[]; host: string | null; auth_mode: string; auth_header: string; materialization: string; target_schema: string | null; last_test: ConnResult | null; ai: { connection: string | null; kind: string; deployment: string | null } | null; connections_backend?: "local" | "hub" | "none"; missing_connection_id?: string | null }
export interface DomainSettingsPatch { description?: string; review_quorum?: number; base_iri?: string; connection_id?: string | null; ai_connection_id?: string | null; default_catalog?: string | null; schemas?: string[]; default_schema?: string | null; sources?: SourceInput[]; materialization?: "none" | "view" | "table"; target_schema?: string | null }
export interface Task { title: string; sub: string; when: string; icon: string; go: { screen: string; domain?: string; version?: number } }
export interface Principal { name: string; role: Role; seen: string }
export interface ApiKey { name: string; prefix: string; role: Role }
export interface Lock { what: string; who: string; exp: string }

export interface NewDomainInput { name: string; description: string; base_iri: string; quorum: number; ai_connection_id?: string | null; sources?: SourceInput[] }

// The port every adapter implements. Screens only ever talk to this.
export interface DatagraphApi {
  config(): Promise<Config>;
  me(): Promise<Me>;
  domains(): Promise<DomainSummary[]>;
  domain(name: string): Promise<DomainSummary>;
  createDomain(input: NewDomainInput): Promise<DomainSummary>;
  audit(domain: string): Promise<AuditEntry[]>;
  comments(domain: string): Promise<Comment[]>;
  addComment(domain: string, text: string): Promise<Comment[]>;
  transition(domain: string, version: number, to: VersionStatus | "active"): Promise<DomainSummary>;
  createDraft(domain: string, from?: number): Promise<DomainSummary>;
  review(domain: string, version: number, approved: boolean, comment?: string): Promise<DomainSummary>;   // a rejection sends the version back to draft
  takeLease(domain: string, version: number, force?: boolean): Promise<DomainSummary>;
  releaseLease(domain: string, version: number): Promise<DomainSummary>;
  deleteDraft(domain: string, version: number): Promise<DomainSummary>;
  exportBundle(domain: string, version: number): Promise<unknown>;   // portable JSON of one version, for download
  setMcp(domain: string, exposed: boolean): Promise<void>;

  schemas(domain: string): Promise<{ id: string; label: string; group?: string }[]>;   // the domain's own schemas, labelled for the picker and grouped by connection
  catalogSchemas(domain: string): Promise<string[]>;                     // what the source offers, for choosing them
  catalogTables(domain: string, schema: string, version?: number): Promise<CatalogTable[]>;   // with a version: marks what its snapshot holds
  snapshot(domain: string, version: number): Promise<SnapshotTable[]>;
  importTables(domain: string, version: number, schema: string, tables: string[]): Promise<SnapshotTable[]>;   // the scan: capture columns, keys and comments into the draft
  refreshSnapshot(domain: string, version: number): Promise<RefreshChange[]>;
  removeTable(domain: string, version: number, table: string): Promise<void>;   // drop one table (its snapshot name) from the draft's snapshot
  tableDetail(domain: string, schema: string, table: string): Promise<TableDetail>;
  tableProfile(domain: string, version: number, table: string): Promise<TableProfile | null>;                       // the saved profile, or null before the first run
  runProfile(domain: string, version: number, table: string, onProgress?: (p: AiProgress) => void): Promise<TableProfile>;
  tableDq(domain: string, version: number, table: string): Promise<DqStatus>;
  dqKinds(): Promise<DqKindInfo[]>;                                            // the catalogue of rule kinds (DQX-style)
  dqOverview(domain: string, version: number): Promise<DqOverview>;            // every table with rules, every rule, across the version
  runDq(domain: string, version: number, table: string, onProgress?: (p: AiProgress) => void): Promise<DqRun>;
  addRule(domain: string, version: number, table: string, rule: RuleInput): Promise<DqRule>;
  updateRule(ruleId: string, patch: Partial<RuleInput>): Promise<DqRule>;
  deleteRule(ruleId: string): Promise<void>;
  suggestRules(domain: string, version: number, table: string, onProgress?: (p: AiProgress) => void): Promise<{ added: number; skipped: string[] }>;
  autoSuggestRules(domain: string, version: number, table: string): Promise<{ added: number; skipped: string[] }>;             // rules read off the profile, no AI
  ruleFailures(ruleId: string, limit?: number): Promise<FailingRows>;                                                   // a sample of the source rows that break a row-level rule
  suggestTerms(domain: string, version: number, table: string, onProgress?: (p: AiProgress) => void): Promise<{ added: number; skipped: string[] }>;
  chat(message: string, ctx: AssistantContext, conversationId: string | null, onEvent?: (e: ChatEvent) => void): Promise<ChatResult>;   // the assistant answers through the MCP tools; events arrive as it works
  conversations(domain?: string): Promise<Conversation[]>;
  conversation(id: string): Promise<Conversation & { messages: ChatMessage[] }>;
  deleteConversation(id: string): Promise<void>;
  glossary(domain: string, opts?: { kind?: "term" | "metric"; table?: string; q?: string }): Promise<GlossaryEntry[]>;
  addTerm(domain: string, term: TermInput): Promise<GlossaryEntry>;
  updateTerm(id: string, patch: Partial<TermInput>): Promise<GlossaryEntry>;
  deleteTerm(id: string): Promise<void>;
  tableClass(domain: string, table: string, version?: number): Promise<string | null>;

  ontology(domain: string, version: number): Promise<OntoClass[]>;
  draftOntology(domain: string, version: number, opts: { ai: boolean; description?: string; tables?: string[] }, onProgress?: (p: AiProgress) => void): Promise<{ classes: number; properties: number; warnings: number }>;   // replaces the draft's ontology: with the AI provider from the snapshot, or heuristically from the tables
  ontologyChecks(domain: string, version: number): Promise<OntoCheck[]>;

  mapping(domain: string, version: number): Promise<Record<string, ClassMapping>>;
  mappingKpis(domain: string, version: number): Promise<MappingKpis>;
  tablePreview(domain: string, cls: string, version?: number): Promise<TablePreview>;
  classSql(domain: string, cls: string, version?: number): Promise<string>;
  // the mapping editor: every change goes through the version's mapping spec
  mapClass(domain: string, version: number, cls: string, table: string, key: string[]): Promise<void>;
  bindAttribute(domain: string, version: number, cls: string, attr: string, column: string | null): Promise<void>;
  excludeProperty(domain: string, version: number, cls: string, prop: string, excluded: boolean): Promise<void>;
  mapRelation(domain: string, version: number, cls: string, rel: string, sourceKey: string[], targetKey: string[]): Promise<void>;
  unmapClass(domain: string, version: number, cls: string): Promise<void>;
  excludeUnmapped(domain: string, version: number): Promise<void>;
  drift(domain: string, version: number, opts?: { live?: boolean }): Promise<DriftIssue[]>;   // what the last build found; live re-reads the source (slow)
  r2rml(domain: string, version: number): Promise<string>;
  suggestMapping(domain: string, version: number, onProgress?: (p: AiProgress) => void): Promise<{ classes: number; relations: number; skipped: string[] }>;   // skipped: suggestions naming things the ontology or tables do not have
  suggestRelations(domain: string, version: number, onProgress?: (p: AiProgress) => void): Promise<{ added: number; declared: number; byName: number; ai: number; skipped: string[]; unmappable: string[] }>;   // fills unmapped relationships: declared keys, matching names, then the AI per pair of tables
  runningAiJob(domain: string, version: number, kind: "suggest-mapping" | "draft-ontology" | "suggest-relations", onProgress?: (p: AiProgress) => void): Promise<AiProgress | null>;   // a job started earlier (or from another tab): followed to its end, null when none is running

  rules(domain: string, version: number): Promise<Rule[]>;
  constraints(domain: string, version: number): Promise<Constraint[]>;

  builds(domain: string, version: number): Promise<BuildRun[]>;
  startBuild(domain: string, version: number, opts?: { full?: boolean }): Promise<BuildRun>;   // full: read every source table again instead of only the changed ones
  buildStatus(runId: string): Promise<BuildRun>;
  cancelBuild(runId: string): Promise<BuildRun>;
  checklist(domain: string, version: number): Promise<ChecklistItem[]>;

  search(domain: string, q: string, opts?: SearchOptions): Promise<SearchHit[]>;
  entity(domain: string, id: string): Promise<EntityDetail>;
  graphStatus(domain: string): Promise<GraphStatus>;
  graphOverview(domain: string, limit?: number): Promise<GraphSample>;   // a first picture of the whole graph: a few relationships of every predicate
  triples(domain: string, query: TripleQuery): Promise<TriplePage>;
  analytics(domain: string): Promise<Analytics>;

  testConnection(): Promise<ConnResult>;               // the deployment's env source (no connection attached)
  connectors(): Promise<ConnectorSpec[]>;             // read from the connection module (the hub)
  connections(): Promise<ConnectionRec[]>;            // read from the hub; creating/editing is @polestar/connections' job
  testConnectionById(id: string): Promise<ConnResult>;
  detachConnection(id: string): Promise<void>;         // clear domain references after the package deleted it in the hub
  updateDomain(domain: string, patch: DomainSettingsPatch): Promise<DomainSummary>;
  sourceFacts(domain: string): Promise<SourceFacts>;
  tasks(): Promise<Task[]>;
  principals(): Promise<Principal[]>;
  apiKeys(): Promise<ApiKey[]>;
  locks(): Promise<Lock[]>;
}

export const STATUS_LABEL: Record<VersionStatus, string> = { draft: "draft", in_review: "in review", published: "published", archived: "archived" };
export const STATUS_COLOR: Record<VersionStatus, string> = { draft: "#B3B3B7", in_review: "#FF7000", published: "#2249FF", archived: "#CFCFD2" };
export const STATE_COLOR: Record<MappingState, string> = { complete: "#2249FF", partial: "#FF7000", unmapped: "#B3B3B7" };

/** Warehouse-qualified table name for the running adapter (three-part on Databricks). */
export function tableName(kind: SourceKind, catalog: string, schema: string, table: string): string {
  return kind === "databricks" ? `${catalog}.${schema}.${table}` : `${catalog}_${schema}.${table}`;
}

/** Compile a class mapping to triple-producing SQL in the adapter's dialect (mirrors the backend compiler's output shape). */
export function compileClassSql(kind: SourceKind, baseIri: string, cls: string, m: ClassMapping, catalog = "rgm"): string {
  const dbx = kind === "databricks";
  const q = (c: string) => (dbx ? `\`${c}\`` : `"${c}"`);
  const tbl = m.table ? (dbx ? `\`${catalog}\`.\`${m.table[0]}\`.\`${m.table[1]}\`` : `"${catalog}_${m.table[0]}"."${m.table[1]}"`) : `(${m.sql}) AS q`;
  const ns = baseIri.replace(/\/$/, "");
  const iri = dbx
    ? `concat('${baseIri}${cls}/', url_encode(CAST(${q(m.key)} AS STRING)))`
    : `'${baseIri}${cls}/' || ontoforge_iri_encode(${q(m.key)}::text)`;
  const parts = [`SELECT ${iri} AS s,\n       'http://www.w3.org/1999/02/22-rdf-syntax-ns#type' AS p,\n       '${ns}#${cls}' AS o\nFROM ${tbl}`];
  for (const [a, c] of Object.entries(m.cols)) parts.push(`SELECT ${iri},\n       '${ns}#${a}', CAST(${q(c)} AS ${dbx ? "STRING" : "text"})\nFROM ${tbl}`);
  return parts.join("\nUNION ALL\n") + ";";
}
