// In-memory adapter carrying the design's data. Mutations are kept in memory so the
// UI behaves like the real thing (lifecycle transitions, builds with live steps, comments).
import * as D from "./mockData";
import { compileClassSql, tableName } from "./types";
import type { AiProgress, DomainSource, DriftIssue, GraphSample, SearchOptions, RefreshChange, SnapshotTable, SourceFactsEntry, SourceInput,
  Analytics, ApiKey, AuditEntry, BuildRun, BuildStep, CatalogTable, ChecklistItem, ClassMapping, Comment, Config, ConnResult, Constraint,
  DatagraphApi, DomainSummary, DqColumnIssue, EntityDetail, GlossaryTerm, GraphStatus, Lock, MappingKpis, Me, NewDomainInput, OntoCheck,
  OntoClass, OntoDiff, Principal, Role, Rule, SearchHit, SourceKind, TableDetail, TablePreview, TableProfile, Task, TriplePage, TripleQuery,
  VersionStatus, ConnectorSpec, ConnectionRec, SourceFacts, DomainSettingsPatch,
} from "./types";

export interface MockOptions { sourceKind?: SourceKind; role?: Role; catalogDenied?: boolean; latency?: number; stepScale?: number }

const clone = <T>(x: T): T => JSON.parse(JSON.stringify(x));

export class MockApi implements DatagraphApi {
  private domainsState: DomainSummary[] = clone(D.DOMAINS);
  private commentStore: Record<string, Comment[]> = Object.fromEntries(Object.entries(D.COMMENTS).map(([k, v]) => [k, v.map(([who, when, text]) => ({ who, when, text }))]));
  private runs: Record<string, BuildRun[]> = {};
  private live: Record<string, { run: BuildRun; timers: ReturnType<typeof setTimeout>[] }> = {};
  private nextRun = 0xb105;
  private conns: ConnectionRec[] = [];
  private snapshots: Record<string, Set<string>> = {};
  private maps: Record<string, Record<string, ClassMapping>> = {};
  private ontos: Record<string, OntoClass[]> = {};   // domains created in this session start without an ontology   // domain -> editable copy of the design mapping   // "domain:version" -> qualified table names imported on top of the design data
  readonly kind: SourceKind;
  readonly role: Role;
  protected mockOpts: MockOptions;

  constructor(opts: MockOptions = {}) {
    this.mockOpts = opts;
    this.kind = opts.sourceKind ?? "databricks";
    this.role = opts.role ?? "admin";
    this.conns = clone(D.CONNECTIONS(this.kind));
    for (const d of this.domainsState) { d.aiConnectionId = d.name === "finops" ? null : "c-gpt"; d.targetSchema = d.target; this.syncSources(d); }
  }

  /** The single-source fields mirror the primary (first) source. */
  private syncSources(d: DomainSummary) {
    const p = d.sources[0];
    d.connectionId = p?.connectionId ?? null;
    d.catalog = p?.catalog ?? d.catalog;
    d.schemas = p ? [...p.schemas] : [];
    d.schema = d.schemas[0] ?? "";
  }
  private cleanSources(sources: SourceInput[]): DomainSource[] {
    const seen = new Set<string>();
    return sources.map(src => {
      const cid = (src.connection_id ?? "").trim() || null;
      if (cid) { if (seen.has(cid)) throw new Error(`Connection ${cid} is listed twice; give it all its schemas in one source`); if (!this.conns.some(c => c.id === cid)) throw new Error(`Connection ${cid} not found`); seen.add(cid); }
      return { connectionId: cid, catalog: (src.catalog ?? "").trim() || null, schemas: [...new Set(src.schemas.map(x => x.trim()).filter(Boolean))] };
    });
  }
  private simulateTest(kind: string, config: Record<string, string | number>): ConnResult {
    const dbx = kind === "databricks";
    if (dbx && this.mockOpts.catalogDenied) return { ok: false, title: "Connection failed", detail: "[INSUFFICIENT_PERMISSIONS] User does not have USE CATALOG on Catalog 'finops_metadata'.", action: "Ask the workspace admin for USE CATALOG / USE SCHEMA / SELECT on the catalog for this principal.", latency_ms: 1620 };
    if (kind === "sqlserver") return { ok: false, title: "Driver not installed", detail: "Neither pyodbc nor pymssql is installed in this deployment.", action: "Install a driver: pip install pyodbc (needs the Microsoft ODBC Driver 18) or pip install pymssql.", latency_ms: 2 };
    if (!config.host && !config.endpoint) return { ok: false, title: "Connection failed", detail: "host is required", latency_ms: 1 };
    if (kind === "azure_openai") return { ok: true, title: "Connected", detail: `42 models available · deployment ${config.deployment ?? "—"}`, latency_ms: 410 };
    if (kind === "postgres") return { ok: true, title: "Connected", detail: `PostgreSQL 16.4 · 17 tables in ${config.schema ?? "public"}`, latency_ms: 38 };
    return { ok: true, title: "Connected", detail: `alice on ${config.catalog ?? "hive_metastore"}.${config.schema ?? "default"} · 17 tables`, latency_ms: 1842 };
  }
  async connectors(): Promise<ConnectorSpec[]> { return clone(D.CONNECTOR_SPECS); }
  async connections(): Promise<ConnectionRec[]> { return clone(this.conns); }
  async testConnectionById(id: string): Promise<ConnResult> {
    const c = this.conns.find(x => x.id === id); if (!c) throw new Error(`Connection ${id} not found`);
    await new Promise(r => setTimeout(r, this.mockOpts.latency ?? (c.kind === "databricks" ? 900 : 200)));
    const r = this.simulateTest(c.kind, c.config); c.last_test = { ...r, at: new Date().toISOString() }; return r;
  }
  async detachConnection(id: string): Promise<void> {
    for (const d of this.domainsState) { d.sources = d.sources.filter(s => s.connectionId !== id); if (d.aiConnectionId === id) d.aiConnectionId = null; this.syncSources(d); }
  }
  async updateDomain(domain: string, patch: DomainSettingsPatch): Promise<DomainSummary> {
    const d = this.dom(domain);
    if (patch.materialization && !["none", "view", "table"].includes(patch.materialization)) throw new Error("materialization must be one of none, view, table");
    if (patch.description !== undefined) d.description = patch.description;
    if (patch.review_quorum !== undefined) d.quorum = patch.review_quorum;
    if (patch.base_iri !== undefined) d.base_iri = patch.base_iri;
    if (patch.connection_id !== undefined) d.connectionId = patch.connection_id;
    if (patch.ai_connection_id !== undefined) { if (!patch.ai_connection_id) throw new Error("An AI connection is required: pick one for this domain"); if (!this.conns.some(c => c.id === patch.ai_connection_id)) throw new Error(`Connection ${patch.ai_connection_id} not found`); d.aiConnectionId = patch.ai_connection_id; }
    if (patch.sources !== undefined) d.sources = this.cleanSources(patch.sources);
    // legacy single-source keys act on the primary source
    if (patch.connection_id !== undefined) {
      const cid = patch.connection_id || null; const idx = d.sources.findIndex(s => cid && s.connectionId === cid);
      if (idx >= 0) d.sources.unshift(...d.sources.splice(idx, 1)); else if (d.sources[0]) d.sources[0].connectionId = cid; else d.sources.push({ connectionId: cid, catalog: null, schemas: [] });
    }
    if (!d.sources.length && (patch.default_catalog !== undefined || patch.schemas !== undefined || patch.default_schema !== undefined)) d.sources.push({ connectionId: null, catalog: null, schemas: [] });
    const primary = d.sources[0];
    if (patch.default_catalog !== undefined && primary) primary.catalog = patch.default_catalog || null;
    if (patch.schemas !== undefined && primary) primary.schemas = [...new Set(patch.schemas.map(x => x.trim()).filter(Boolean))];
    if (patch.default_schema !== undefined && primary) { const first = (patch.default_schema ?? "").trim(); primary.schemas = (first ? [first] : []).concat(primary.schemas.filter(x => x !== first)); }
    this.syncSources(d);
    if (patch.materialization !== undefined) d.materialization = patch.materialization;
    if (patch.target_schema !== undefined) { d.targetSchema = patch.target_schema; d.target = patch.target_schema ?? ""; }
    return clone(d);
  }
  async sourceFacts(domain: string): Promise<SourceFacts> {
    const d = this.dom(domain); const a = this.conns.find(x => x.id === d.aiConnectionId) ?? null;
    const dbx = this.kind === "databricks";
    const describe = (src: DomainSource): SourceFactsEntry => {
      const c = src.connectionId ? this.conns.find(x => x.id === src.connectionId) ?? null : null;
      if (c) return { kind: c.kind, connection: c.name, connection_id: c.id, catalog: src.catalog || String(c.config.catalog ?? "") || null, schemas: [...src.schemas], host: String(c.config.host ?? c.config.endpoint ?? "") || null, last_test: c.last_test, missing_connection_id: null };
      return { kind: this.kind, connection: null, connection_id: null, catalog: src.catalog || (dbx ? "finops_metadata" : null), schemas: [...src.schemas], host: null, last_test: null, missing_connection_id: src.connectionId };
    };
    const sources = d.sources.map(describe);
    const primary = sources[0] ?? describe({ connectionId: null, catalog: null, schemas: [] });
    return { ...primary, schema: primary.schemas[0] ?? null, sources, auth_mode: "header", auth_header: dbx ? "X-Forwarded-Email" : "X-Actor", materialization: d.materialization.split(" ")[0] || "none", target_schema: d.targetSchema ?? d.target ?? null,
      ai: a ? { connection: a.name, kind: a.kind, deployment: String(a.config.deployment ?? "") } : null };
  }

  private async wait<T>(value: T, ms = this.mockOpts.latency ?? 0): Promise<T> {
    if (ms) await new Promise(r => setTimeout(r, ms));
    return value;
  }
  private dom(name: string): DomainSummary {
    const d = this.domainsState.find(x => x.name === name);
    if (!d) throw new Error(`Domain ${name} not found`);
    return d;
  }

  async config(): Promise<Config> {
    const dbx = this.kind === "databricks";
    return { sourceKind: this.kind, catalog: dbx ? "finops_metadata" : null, authMode: "header", authHeader: dbx ? "X-Forwarded-Email" : "X-Actor", materialization: dbx ? "view" : "view", capabilities: { profiling: true, quality: true, glossary: true, ontoDiffs: true } };
  }
  async me(): Promise<Me> { return { name: "alice", role: this.role }; }
  async domains() { return this.wait(clone(this.domainsState)); }
  async domain(name: string) { return this.wait(clone(this.dom(name))); }
  async createDomain(input: NewDomainInput): Promise<DomainSummary> {
    if (!/^[A-Za-z0-9_-]+$/.test(input.name)) throw new Error("Name may contain letters, digits, - and _ only");
    if (this.domainsState.some(d => d.name === input.name)) throw new Error(`Domain ${input.name} already exists`);
    if (!input.ai_connection_id) throw new Error("An AI connection is required: pick one for this domain");
    if (!this.conns.some(c => c.id === input.ai_connection_id)) throw new Error(`Connection ${input.ai_connection_id} not found`);
    const d: DomainSummary = { name: input.name, description: input.description, base_iri: input.base_iri, quorum: input.quorum, schema: "", schemas: [], sources: this.cleanSources(input.sources ?? []), catalog: input.name, materialization: "view", target: `finops_metadata.${input.name}_graph`, mcpExposed: false, disabledTools: [], triples: "—", lastBuild: "never", versions: [], lease: null, review: null, aiConnectionId: input.ai_connection_id };
    this.syncSources(d);
    this.domainsState.push(d); this.commentStore[d.name] = [];
    return clone(d);
  }
  async audit(domain: string): Promise<AuditEntry[]> { return (D.AUDIT[domain] || []).map(([who, what, version, when]) => ({ who, what, version, when })); }
  async comments(domain: string) { return clone(this.commentStore[domain] || []); }
  async addComment(domain: string, text: string) { (this.commentStore[domain] ||= []).push({ who: "alice", when: "just now", text }); return this.comments(domain); }
  private ver(domain: string, version: number) {
    const d = this.dom(domain);
    const v = d.versions.find(x => x.version === version);
    if (!v) throw new Error(`v${version} not found`);
    return { d, v };
  }
  /** Domain-level lease and review mirror the draft and the version in review. */
  private sync(d: DomainSummary) {
    d.lease = d.versions.find(v => v.status === "draft")?.lease ?? null;
    d.review = d.versions.find(v => v.status === "in_review")?.review ?? null;
    return clone(d);
  }
  async transition(domain: string, version: number, to: VersionStatus | "active") {
    const { d, v } = this.ver(domain, version);
    if (to === "active") { if (v.status !== "published") throw new Error("Only a published version can be served"); d.versions.forEach(x => { x.active = false; }); v.active = true; return this.sync(d); }
    const allowed: Record<VersionStatus, VersionStatus[]> = { draft: ["in_review"], in_review: ["draft", "published"], published: ["archived"], archived: [] };
    if (!allowed[v.status].includes(to)) throw new Error(`Cannot move from ${v.status} to ${to}`);
    if (to === "published" && (v.review?.approved ?? 0) < d.quorum) throw new Error(`Publishing needs ${d.quorum} approval(s); have ${v.review?.approved ?? 0}`);
    if (to === "draft" && d.versions.some(x => x.status === "draft" && x !== v)) throw new Error("Another draft exists for this domain");
    v.status = to;
    if (to === "draft") v.review = null;
    if (to === "in_review") { v.lease = null; v.review = { approved: 0, rejected: 0, quorum: d.quorum, round: (v.review?.round ?? 0) + 1, rows: [] }; }
    if (to === "archived") v.active = false;
    return this.sync(d);
  }
  async review(domain: string, version: number, approved: boolean, comment?: string) {
    const { d, v } = this.ver(domain, version);
    if (v.status !== "in_review") throw new Error("Reviews can only be added while a version is in review");
    const me = (await this.me()).name;
    const rv = v.review ?? { approved: 0, rejected: 0, quorum: d.quorum, round: 1, rows: [] };
    rv.rows = rv.rows.filter(r => r.who !== me);
    rv.rows.push({ who: me, note: comment ?? "", state: approved ? "approved" : "rejected", when: "just now" });
    rv.approved = rv.rows.filter(r => r.state === "approved").length;
    rv.rejected = rv.rows.filter(r => r.state === "rejected").length;
    rv.quorum = d.quorum;
    v.review = rv;
    if (!approved) {
      (this.commentStore[domain] ||= []).push({ who: me, when: "just now", text: `Rejected: ${comment ?? "no reason given"}` });
      return this.transition(domain, version, "draft");
    }
    return this.sync(d);
  }
  async takeLease(domain: string, version: number, force = false) {
    const { d, v } = this.ver(domain, version);
    if (v.status !== "draft") throw new Error("Only a draft can be leased");
    const me = (await this.me()).name;
    if (v.lease && v.lease.holder !== me && !force) throw new Error(`Version is being edited by ${v.lease.holder}`);
    v.lease = { holder: me, expires: "15 min" };
    return this.sync(d);
  }
  async releaseLease(domain: string, version: number) {
    const { d, v } = this.ver(domain, version);
    const me = (await this.me()).name;
    if (v.lease && v.lease.holder !== me) throw new Error(`Lease is held by ${v.lease.holder}`);
    v.lease = null;
    return this.sync(d);
  }
  async exportBundle(domain: string, version: number): Promise<unknown> {
    const { d, v } = this.ver(domain, version);
    return { format: "datagraph.bundle/1", domain: { name: d.name, description: d.description, base_iri: d.base_iri }, versions: [clone(v)] };
  }
  async deleteDraft(domain: string, version: number) {
    const { d, v } = this.ver(domain, version);
    if (v.status !== "draft") throw new Error("Only draft versions can be deleted");
    d.versions = d.versions.filter(x => x !== v);
    return this.sync(d);
  }
  async createDraft(domain: string, from?: number) {
    const d = this.dom(domain);
    const src = d.versions.find(v => v.version === from) || d.versions.find(v => v.active) || d.versions[0];
    const n = (d.versions[0]?.version || 0) + 1;
    d.versions.unshift({ version: n, status: "draft", content: src ? src.content : "empty", mappingPct: src?.mappingPct ?? null, lastBuild: "never", active: false, created: "just now", by: "alice", stats: src ? { ...src.stats, triples: 0 } : { classes: 0, attrs: 0, rels: 0, bindings: 0, rules: 0, constraints: 0, triples: 0 }, lease: { holder: "alice", expires: "15 min" }, changes: src ? [{ sign: "+", text: `draft created from v${src.version}` }] : [] });
    return this.sync(d);
  }
  async setMcp(domain: string, exposed: boolean) { this.dom(domain).mcpExposed = exposed; }

  async schemas(domain: string): Promise<{ id: string; label: string; group?: string }[]> {
    const d = this.dom(domain);
    return d.sources.flatMap(src => { const c = this.conns.find(x => x.id === src.connectionId); const dbx = (c?.kind ?? this.kind) === "databricks"; const cat = src.catalog || (dbx ? d.catalog : null);
      const schemas = src.schemas.length ? src.schemas : Object.keys(D.CATALOG);   // none chosen: every schema the source offers
      return schemas.map(sch => ({ id: dbx && cat ? `${cat}.${sch}` : sch, label: `${dbx && cat ? `${cat}.` : ""}${sch}`, group: c?.name ?? "deployment default" })); });
  }
  async catalogSchemas(domain: string) { return [...new Set([...Object.keys(D.CATALOG), ...this.dom(domain).schemas])]; }
  async catalogTables(domain: string, schema: string, version?: number): Promise<CatalogTable[]> {
    if (this.kind === "databricks" && this.mockOpts.catalogDenied) throw new Error("[INSUFFICIENT_PERMISSIONS] User does not have USE CATALOG on Catalog 'finops_metadata'.");
    const plain = schema.split(".").pop() ?? schema;
    const extra = version !== undefined ? this.snapshots[`${domain}:${version}`] : undefined;
    return this.wait((D.CATALOG[plain] || []).map(([name, cols, imported]) => ({ name, cols, imported: imported || !!extra?.has(`${schema}.${name}`), cls: D.TABLE_CLASS[name] || null })));
  }
  async snapshot(domain: string, version: number): Promise<SnapshotTable[]> {
    const { d } = this.ver(domain, version);
    const describe = (table: string, cols: number): SnapshotTable => { const name = table.split(".").pop() ?? table; const c = (D.COLUMNS[name] || D.GENERIC_COLS).cols; return { table, columns: cols || c.length, columnNames: c.map(x => x[0]), comment: null, primaryKey: c.filter(x => x[3] === "pk").map(x => x[0]) }; };
    const design = d.sources.flatMap(src => src.schemas.flatMap(sch => (D.CATALOG[sch] || []).filter(([, , imported]) => imported).map(([name, cols]) => describe(`${src.catalog ? src.catalog + "." : ""}${sch}.${name}`, cols))));
    const extra = [...(this.snapshots[`${domain}:${version}`] ?? [])].map(t => describe(t, D.CATALOG[t.split(".").slice(-2)[0]]?.find(([n]) => n === t.split(".").pop())?.[1] ?? 0));
    return [...design, ...extra];
  }
  async importTables(domain: string, version: number, schema: string, tables: string[]): Promise<SnapshotTable[]> {
    const { v } = this.ver(domain, version);
    if (v.status !== "draft") throw new Error("Only draft versions can be edited");
    if (v.lease && v.lease.holder !== (await this.me()).name) throw new Error(`Version is being edited by ${v.lease.holder}`);
    const set = (this.snapshots[`${domain}:${version}`] ||= new Set());
    for (const t of tables) set.add(`${schema}.${t}`);
    return this.snapshot(domain, version);
  }
  async refreshSnapshot(_domain: string, _version: number): Promise<RefreshChange[]> { return []; }
  async tableDetail(domain: string, schemaId: string, table: string): Promise<TableDetail> {
    const schema = schemaId.split(".").pop() ?? schemaId;
    const d = this.dom(domain); const ct = D.COLUMNS[table] || D.GENERIC_COLS;
    return { name: table, fullName: tableName(this.kind, d.catalog, schema, table), comment: ct.comment, columns: ct.cols.map(([name, type, comment, k]) => ({ name, type, comment, key: k || null, keyInferred: this.kind === "databricks" })) };
  }
  async tableProfile(_domain: string, table: string): Promise<TableProfile> { return this.wait(D.PROFILE[table] || { rows: "—", fresh: "—", dup: "—", cols: {} }, 400); }
  async tableDq(_domain: string, table: string): Promise<DqColumnIssue[]> {
    const ct = D.COLUMNS[table] || D.GENERIC_COLS;
    return ct.cols.filter(c => D.DQ_BY_COL[c[0]]).map(c => ({ column: c[0], count: D.DQ_BY_COL[c[0]][0], kind: D.DQ_BY_COL[c[0]][1] }));
  }
  async glossary(_domain: string): Promise<GlossaryTerm[]> { return clone(D.GLOSSARY); }
  async ontoDiffs(_domain: string, table: string): Promise<OntoDiff[]> { return clone(D.ONTO_DIFFS[table] || []); }
  async tableClass(_domain: string, table: string, _version?: number) { return D.TABLE_CLASS[table] || null; }

  async ontology(domain: string, _version: number): Promise<OntoClass[]> { return clone(this.ontos[domain] ?? (D.DOMAINS.some(d => d.name === domain) ? D.CLASSES : [])); }
  private async stages(onProgress: ((p: AiProgress) => void) | undefined, lines: string[], ms: number) {
    const startedAt = new Date().toISOString();
    for (const progress of lines) { onProgress?.({ progress, startedAt, progressAt: new Date().toISOString(), status: "running" }); await this.wait(null, ms); }
  }
  async draftOntology(domain: string, _version: number, opts: { ai: boolean; description?: string; tables?: string[] }, onProgress?: (p: AiProgress) => void) {
    const n = opts.tables?.length ?? 3;
    await this.stages(onProgress, opts.ai ? [`Describing table 1 of ${n}: dim_customer`, `Asking the AI provider to draft the ontology from ${n} table(s)`] : [`Deriving classes from ${n} table(s)`], this.mockOpts.latency ?? (opts.ai ? 400 : 100));
    this.ontos[domain] = clone(D.CLASSES);
    return { classes: D.CLASSES.length, properties: D.CLASSES.reduce((a, c) => a + c.attrs.length + c.rels.length, 0), warnings: opts.ai ? 1 : 0 };
  }
  async ontologyChecks(_domain: string, _version: number): Promise<OntoCheck[]> { return clone(D.CHECKS); }

  private mapOf(domain: string): Record<string, ClassMapping> { return (this.maps[domain] ||= clone(D.MAP)); }
  private attrsOf(cls: string): string[] { return D.CLASSES.find(c => c.id === cls)?.attrs.map(a => a.name) ?? []; }
  private relsOf(cls: string): { name: string; target: string }[] { return D.CLASSES.find(c => c.id === cls)?.rels ?? []; }
  private restate(m: ClassMapping, cls: string): ClassMapping {
    const ex = new Set(m.excluded ?? []);
    const open = this.attrsOf(cls).filter(a => !m.cols[a] && !ex.has(a)).length + this.relsOf(cls).filter(r => !m.rels?.[r.name] && !ex.has(r.name)).length;
    return { ...m, state: !m.table && !m.sql ? "unmapped" : open ? "partial" : "complete" };
  }
  async mapping(domain: string, _version: number): Promise<Record<string, ClassMapping>> {
    return Object.fromEntries(Object.entries(this.mapOf(domain)).map(([cls, m]) => [cls, clone(this.restate(m, cls))]));
  }
  async mappingKpis(domain: string, _version: number): Promise<MappingKpis> {
    const M = this.mapOf(domain);
    const classes = D.CLASSES.length, mapped = Object.values(M).filter(m => m.table || m.sql).length;
    const attrs = D.CLASSES.reduce((a, c) => a + c.attrs.length, 0), rels = D.CLASSES.reduce((a, c) => a + c.rels.length, 0);
    const boundA = Object.values(M).reduce((a, m) => a + Object.keys(m.cols).length, 0), boundR = Object.values(M).reduce((a, m) => a + Object.keys(m.rels ?? {}).length, 0);
    const excluded = Object.values(M).reduce((a, m) => a + (m.excluded?.length ?? 0), 0);
    const denom = classes + attrs + rels;
    return { completion: denom ? Math.round(((mapped + boundA + boundR + excluded) / denom) * 100) : 0, classesMapped: [mapped, classes], attributes: [boundA, attrs], relationships: [boundR, rels], excluded };
  }
  async mapClass(domain: string, _version: number, cls: string, table: string, key: string[]): Promise<void> {
    const parts = table.split("."); const M = this.mapOf(domain);
    M[cls] = { ...(M[cls] ?? { cols: {}, state: "partial" }), table: [parts.length > 1 ? parts[parts.length - 2] : "", parts[parts.length - 1]], fullName: table, key: key[0] ?? "", cols: M[cls]?.fullName === table ? M[cls].cols : {}, state: "partial" };
  }
  async bindAttribute(domain: string, _version: number, cls: string, attr: string, column: string | null): Promise<void> {
    const m = this.mapOf(domain)[cls]; if (!m) throw new Error(`${cls} is not mapped to a table yet`);
    if (column) m.cols[attr] = column; else delete m.cols[attr];
  }
  async excludeProperty(domain: string, _version: number, cls: string, prop: string, excluded: boolean): Promise<void> {
    const m = this.mapOf(domain)[cls]; if (!m) throw new Error(`${cls} is not mapped to a table yet`);
    const ex = new Set(m.excluded ?? []); if (excluded) ex.add(prop); else ex.delete(prop); m.excluded = [...ex].sort();
    if (excluded) delete m.cols[prop];
  }
  async mapRelation(domain: string, _version: number, cls: string, rel: string, sourceKey: string[], targetKey: string[]): Promise<void> {
    const m = this.mapOf(domain)[cls]; if (!m) throw new Error(`${cls} is not mapped to a table yet`);
    const target = this.relsOf(cls).find(r => r.name === rel)?.target ?? "?";
    (m.rels ||= {})[rel] = `${sourceKey.join(",")} → ${target}.${targetKey.join(",")}`;
  }
  async unmapClass(domain: string, _version: number, cls: string): Promise<void> { delete this.mapOf(domain)[cls]; }
  async excludeUnmapped(domain: string, _version: number): Promise<void> {
    for (const [cls, m] of Object.entries(this.mapOf(domain))) { const ex = new Set(m.excluded ?? []); for (const a of this.attrsOf(cls)) if (!m.cols[a]) ex.add(a); for (const r of this.relsOf(cls)) if (!m.rels?.[r.name]) ex.add(r.name); m.excluded = [...ex].sort(); }
  }
  async drift(_domain: string, _version: number): Promise<DriftIssue[]> {
    return [{ kind: "missing-column", table: "rgm.gold.fct_sales", column: "channel_id", detail: "fct_sales.channel_id has no target table", mapping_ref: "Sale.viaChannel", severity: "error" }];
  }
  async r2rml(domain: string, _version: number): Promise<string> {
    const d = this.dom(domain);
    return ["@prefix rr: <http://www.w3.org/ns/r2rml#> .", `@prefix : <${d.base_iri}> .`, "", ...Object.entries(this.mapOf(domain)).filter(([, m]) => m.table).map(([cls, m]) => `<#${cls}> a rr:TriplesMap ;\n  rr:logicalTable [ rr:tableName "${m.fullName ?? m.table?.join(".")}" ] ;\n  rr:subjectMap [ rr:template "${d.base_iri}${cls}/{${m.key}}" ; rr:class :${cls} ] .`)].join("\n");
  }
  async runningAiJob(_domain: string, _version: number, _kind: "suggest-mapping" | "draft-ontology"): Promise<AiProgress | null> { return null; }
  async suggestMapping(domain: string, version: number, onProgress?: (p: AiProgress) => void): Promise<{ classes: number; relations: number; skipped: string[] }> {
    await this.stages(onProgress, ["Describing table 1 of 10: dim_customer", "Asking the AI provider to map 12 classes onto 10 table(s)"], this.mockOpts.latency ?? 300);
    const M = this.mapOf(domain); let n = 0;
    for (const [table, cls] of Object.entries(D.TABLE_CLASS)) if (!M[cls] && D.CLASSES.some(c => c.id === cls)) { await this.mapClass(domain, version, cls, `${this.dom(domain).catalog}.gold.${table}`, ["id"]); n++; }
    return { classes: n, relations: 0, skipped: [] };
  }
  async tablePreview(_domain: string, cls: string, _version?: number): Promise<TablePreview> { return this.wait(clone(D.PREVIEW[cls] || D.PREVIEW.Customer), this.kind === "databricks" ? 900 : 200); }
  async classSql(domain: string, cls: string, _version?: number) { const m = this.mapOf(domain)[cls]; if (!m) return ""; const d = this.dom(domain); return compileClassSql(this.kind, d.base_iri, cls, m, d.catalog); }

  async rules(_domain: string, _version: number): Promise<Rule[]> { return clone(D.RULES); }
  async constraints(_domain: string, _version: number): Promise<Constraint[]> { return clone(D.CONSTRAINTS); }

  private historicRun(id: string, status: BuildRun["status"], actor: string, duration: string, triples: string, error = ""): BuildRun {
    const ok = status === "succeeded";
    return { id, status, actor, duration, triples, inferred: ok ? "23,207" : "—", error, stepIndex: -1, steps: D.STEP_NAMES.map(([name, detail], i) => ({ name, detail: ok ? detail : (i === 0 && status === "failed" ? "failed" : detail), seconds: ok ? D.STEP_SECS[i] : (i === 0 ? 12.3 : null), state: ok || i === 0 ? "done" : "queued" })) };
  }
  private historyFor(domain: string, version: number): BuildRun[] {
    const key = `${domain}:${version}`;
    if (!this.runs[key]) this.runs[key] = domain === "finops" ? [] : [this.historicRun("#a3f1", "succeeded", "alice", "61.4 s", "263,695"), this.historicRun("#9e02", "failed", "bob", "12.3 s", "—", "compile: relation viaChannel on Sale has no target key"), this.historicRun("#8c77", "succeeded", "alice", "58.9 s", "261,010")];
    return this.runs[key];
  }
  async builds(domain: string, version: number) { return clone(this.historyFor(domain, version)); }
  async startBuild(domain: string, version: number): Promise<BuildRun> {
    const id = `#${(this.nextRun++).toString(16)}`;
    const steps: BuildStep[] = D.STEP_NAMES.map(([name, detail], i) => ({ name, detail, seconds: null, state: i === 0 ? "running" : "queued" }));
    const run: BuildRun = { id, status: "running", actor: "alice", duration: "—", triples: "—", inferred: "—", error: "", steps, stepIndex: 0 };
    const timers: ReturnType<typeof setTimeout>[] = [];
    const scale = this.mockOpts.stepScale ?? 350;
    let acc = 0;
    D.STEP_SECS.forEach((s, i) => {
      acc += Math.min(s, 2.2) * scale + 300;
      timers.push(setTimeout(() => {
        run.steps[i] = { ...run.steps[i], seconds: s, state: "done" };
        const done = i === D.STEP_SECS.length - 1;
        if (done) { run.status = "succeeded"; run.stepIndex = -1; run.duration = `${D.STEP_SECS.reduce((a, b) => a + b, 0).toFixed(1)} s`; run.triples = "263,695"; run.inferred = "23,207"; delete this.live[id]; }
        else { run.stepIndex = i + 1; run.steps[i + 1] = { ...run.steps[i + 1], state: "running" }; }
      }, acc));
    });
    this.live[id] = { run, timers };
    this.historyFor(domain, version).unshift(run);
    return clone(run);
  }
  async buildStatus(runId: string): Promise<BuildRun> {
    const l = this.live[runId]; if (l) return clone(l.run);
    for (const rs of Object.values(this.runs)) { const r = rs.find(x => x.id === runId); if (r) return clone(r); }
    throw new Error(`Run ${runId} not found`);
  }
  async cancelBuild(runId: string) {
    const l = this.live[runId]; if (!l) return this.buildStatus(runId);
    l.timers.forEach(clearTimeout); l.run.status = "cancelled"; l.run.stepIndex = -1; l.run.steps = l.run.steps.map(s => s.state === "running" ? { ...s, state: "queued" } : s); delete this.live[runId];
    return clone(l.run);
  }
  async checklist(_domain: string, _version: number): Promise<ChecklistItem[]> {
    return [{ label: "Mapping completion", value: "78%", ok: false, go: { screen: "mapping" } }, { label: "Ontology checks", value: "0 errors", ok: true, go: { screen: "ontology", arg: "checks" } }, { label: "Schema drift", value: "1 issue", ok: false, go: { screen: "metadata", arg: "fct_sales" } }];
  }

  async search(_domain: string, q: string, opts?: SearchOptions): Promise<SearchHit[]> { const t = q.toLowerCase(); const typeName = opts?.type ? opts.type.split(/[#/]/).pop() : null; const ok = (v: string) => opts?.match === "exact" ? v.toLowerCase() === t : opts?.match === "starts_with" ? v.toLowerCase().startsWith(t) : v.toLowerCase().includes(t); return D.SEARCH.filter(h => (!typeName || h.type === typeName) && (!t || ok(h.label) || ok(h.id))); }
  async entity(_domain: string, id: string): Promise<EntityDetail> { return clone(D.ENTITIES[id] || D.ENTITIES["C-10482"]); }
  async graphOverview(_domain: string, limit = 300): Promise<GraphSample> {
    const hits = D.SEARCH.slice(0, Math.min(limit, D.SEARCH.length));
    const nodes = hits.map(h => ({ id: h.id, label: h.label, type: h.type }));
    const edges = hits.slice(1).map((h, i) => ({ from: hits[i].id, to: h.id, label: i % 2 ? "soldTo" : "ofProduct" }));
    return { nodes, edges };
  }
  async graphStatus(_domain: string): Promise<GraphStatus> { const counts = D.SEARCH.reduce<Record<string, number>>((a, h) => { a[h.type] = (a[h.type] ?? 0) + 1; return a; }, {}); return { triples: "263,695", inferred: "23,207", entities: "12,445", types: Object.entries(counts).map(([name, count]) => ({ name, iri: `http://polestar.ai/rgm#${name}`, count })) }; }
  async triples(_domain: string, qy: TripleQuery): Promise<TriplePage> {
    let rows = D.TRIPLES.filter(t => qy.filter === "all" || (qy.filter === "inferred" ? t[4] : !t[4])).filter(t => !qy.q || t.join(" ").toLowerCase().includes(qy.q.toLowerCase()));
    const ix = { subject: 0, predicate: 1, object: 2, inferred: 4 }[qy.sort];
    rows = [...rows].sort((a, b) => (String(a[ix]) < String(b[ix]) ? -1 : 1) * (qy.dir === "asc" ? 1 : -1));
    return { total: "263,695", rows: rows.slice(qy.offset, qy.offset + qy.limit).map(t => ({ s: t[0], p: t[1], o: t[2], isIri: !!t[3], dt: t[5] || "", inferred: !!t[4] })) };
  }
  async analytics(_domain: string): Promise<Analytics> { return clone(D.ANALYTICS); }

  async testConnection(): Promise<ConnResult> {
    const dbx = this.kind === "databricks";
    await new Promise(r => setTimeout(r, this.mockOpts.latency ?? (dbx ? 1200 : 300)));
    if (dbx && this.mockOpts.catalogDenied) return { ok: false, title: "Permission error", detail: "[INSUFFICIENT_PERMISSIONS] User does not have USE CATALOG on Catalog 'finops_metadata'.", action: "Ask the workspace admin for USE CATALOG / USE SCHEMA / SELECT on finops_metadata for the service principal." };
    return { ok: true, title: "Connected", detail: `GET /catalog/tables → 17 tables in ${dbx ? "1,842" : "38"} ms` };
  }
  async tasks(): Promise<Task[]> { return clone(D.TASKS); }
  async principals(): Promise<Principal[]> { return clone(D.PRINCIPALS); }
  async apiKeys(): Promise<ApiKey[]> { return clone(D.API_KEYS); }
  async locks(): Promise<Lock[]> { return clone(D.LOCKS); }
}
