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
}

export interface Me { name: string; role: Role }

export interface VersionStats { classes: number; attrs: number; rels: number; bindings: number; rules: number; constraints: number; triples: number }
export interface Review { approved: number; quorum: number; rows: { who: string; note: string; state: "approved" | "pending" | "rejected" }[] }
export interface Lease { holder: string; expires: string }

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

export interface DomainSummary {
  name: string;
  description: string;
  base_iri: string;
  quorum: number;
  schema: string;               // default schema for the catalog browser
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
export interface CatalogTable { name: string; cols: number; imported: boolean; cls: string | null }
export interface CatalogColumn { name: string; type: string; comment: string; key: "pk" | "fk" | null; keyInferred: boolean }
export interface TableDetail { name: string; fullName: string; comment: string; columns: CatalogColumn[] }
export interface TableProfile { rows: string; fresh: string; dup: string; cols: Record<string, [number, number]> } // [null %, distinct]
export interface GlossaryTerm { term: string; def: string; cls: string; cols: string[]; steward: string }
export interface OntoDiff { kind: string; column: string; note: string; action: string }
export interface DqColumnIssue { column: string; count: string; kind: string }

// -- ontology ------------------------------------------------------------------------
export interface OntoClass { id: string; iri: string; x: number; y: number; desc: string; parents: string[]; attrs: { name: string; range: string }[]; rels: { name: string; target: string }[] }
export interface OntoCheck { severity: "error" | "warning" | "info"; code: string; subject: string; message: string; target: { screen: "ontology" | "mapping"; cls: string } }

// -- mapping --------------------------------------------------------------------------
export interface ClassMapping { table?: [string, string]; sql?: string; key: string; state: MappingState; cols: Record<string, string>; rels?: Record<string, string> }
export interface MappingKpis { completion: number; classesMapped: [number, number]; attributes: [number, number]; relationships: [number, number]; excluded: number }
export interface TablePreview { columns: string[]; rows: (string | null)[][] }

// -- rules / quality -------------------------------------------------------------------
export interface Rule { name: string; mode: "materialize" | "violation"; text: string; enabled: boolean; lastRun: string }
export interface Constraint { name: string; target: string; kind: string; severity: "violation" | "warning" | "info"; count: number; sample: string; sampleEntity?: string }

// -- build ------------------------------------------------------------------------------
export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export interface BuildStep { name: string; detail: string; seconds: number | null; state: "done" | "running" | "queued" }
export interface BuildRun { id: string; status: RunStatus; actor: string; duration: string; triples: string; inferred: string; error: string; steps: BuildStep[]; stepIndex: number }
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
export interface GraphStatus { triples: string; inferred: string; entities: string }
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
export interface SourceFacts { kind: string; connection: string | null; connection_id: string | null; catalog: string | null; schema: string | null; host: string | null; auth_mode: string; auth_header: string; materialization: string; target_schema: string | null; last_test: ConnResult | null; ai: { connection: string | null; kind: string; deployment: string | null } | null; connections_backend?: "local" | "hub" | "none"; missing_connection_id?: string | null }
export interface DomainSettingsPatch { description?: string; review_quorum?: number; base_iri?: string; connection_id?: string | null; ai_connection_id?: string | null; default_catalog?: string | null; default_schema?: string | null; materialization?: "none" | "view" | "table"; target_schema?: string | null }
export interface Task { title: string; sub: string; when: string; icon: string; go: { screen: string; domain?: string; version?: number } }
export interface Principal { name: string; role: Role; seen: string }
export interface ApiKey { name: string; prefix: string; role: Role }
export interface Lock { what: string; who: string; exp: string }

export interface NewDomainInput { name: string; description: string; base_iri: string; quorum: number }

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
  setMcp(domain: string, exposed: boolean): Promise<void>;

  schemas(domain: string): Promise<{ id: string; label: string }[]>;
  catalogTables(domain: string, schema: string): Promise<CatalogTable[]>;
  tableDetail(domain: string, schema: string, table: string): Promise<TableDetail>;
  tableProfile(domain: string, table: string): Promise<TableProfile>;
  tableDq(domain: string, table: string): Promise<DqColumnIssue[]>;
  glossary(domain: string): Promise<GlossaryTerm[]>;
  ontoDiffs(domain: string, table: string): Promise<OntoDiff[]>;
  tableClass(domain: string, table: string): Promise<string | null>;

  ontology(domain: string, version: number): Promise<OntoClass[]>;
  ontologyChecks(domain: string, version: number): Promise<OntoCheck[]>;

  mapping(domain: string, version: number): Promise<Record<string, ClassMapping>>;
  mappingKpis(domain: string, version: number): Promise<MappingKpis>;
  tablePreview(domain: string, cls: string): Promise<TablePreview>;
  classSql(domain: string, cls: string): Promise<string>;

  rules(domain: string, version: number): Promise<Rule[]>;
  constraints(domain: string, version: number): Promise<Constraint[]>;

  builds(domain: string, version: number): Promise<BuildRun[]>;
  startBuild(domain: string, version: number): Promise<BuildRun>;
  buildStatus(runId: string): Promise<BuildRun>;
  cancelBuild(runId: string): Promise<BuildRun>;
  checklist(domain: string, version: number): Promise<ChecklistItem[]>;

  search(domain: string, q: string): Promise<SearchHit[]>;
  entity(domain: string, id: string): Promise<EntityDetail>;
  graphStatus(domain: string): Promise<GraphStatus>;
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
