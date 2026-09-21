// REST adapter for the datagraph backend (FastAPI, docs/UI-BLUEPRINT.html §8).
// Methods with a settled contract call the API; the rest fall through to the mock so the
// app stays usable while integration proceeds. Replace fallbacks method by method.
import { MockApi } from "./mock";
import type { AuditEntry, BuildRun, CatalogTable, ClassMapping, Comment, Config, ConnResult, ConnectionInput, ConnectionRec, ConnectorSpec, DomainSettingsPatch, DomainSummary, EntityDetail, GraphStatus, Me, NewDomainInput, OntoClass, Principal, Role, SearchHit, SourceFacts, TableDetail, TablePreview, TriplePage, TripleQuery, VersionInfo, VersionStatus } from "./types";
import { tableName } from "./types";

export class ApiError extends Error {
  constructor(public status: number, public detail: string) { super(detail); }
}

export interface RestOptions { base?: string; actor?: string; token?: string }

interface BackendVersion { id: string; version: number; status: VersionStatus; has_ontology: boolean; has_mapping: boolean; rule_count: number; constraint_count: number; created_at?: string; created_by?: string; lease?: { holder: string; expires_at: string } | null }
interface BackendDomain { name: string; description: string | null; base_iri: string; review_quorum: number; active_version_id?: string | null; connection_id?: string | null; ai_connection_id?: string | null; default_catalog?: string | null; default_schema?: string | null; materialization?: string; target_schema?: string | null; mcp_policy?: { exposed?: boolean; disabled_tools?: string[] } }
interface BackendCard { name: string; version_count: number; active_version: { version: number } | null; latest_version: { version: number; status: string } | null; triples: number; last_build: { status: string; finished_at: string | null; triple_count: number | null } | null; source: { kind: string; connection: string | null; catalog: string | null; schema: string | null }; mcp: { exposed: boolean; disabled_tools: string[] } }

export class RestApi extends MockApi {
  private base: string;
  private ropts: RestOptions;
  private versionIds: Record<string, string> = {};   // "domain:3" -> uuid
  private cfg: Config | null = null;

  constructor(opts: RestOptions = {}) {
    super({});
    this.ropts = opts;
    this.base = (opts.base ?? "/api").replace(/\/$/, "");
  }

  private async req<T>(method: string, path: string, body?: unknown, text = false): Promise<T> {
    const headers: Record<string, string> = { Accept: text ? "text/plain" : "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (this.ropts.token) headers.Authorization = `Bearer ${this.ropts.token}`;
    else headers[this.cfg?.authHeader ?? "X-Actor"] = this.ropts.actor ?? "alice";
    const res = await fetch(this.base + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    if (!res.ok) {
      let detail = res.statusText;
      try { const j = await res.json(); detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j); } catch { /* keep statusText */ }
      throw new ApiError(res.status, detail);
    }
    if (res.status === 204) return undefined as T;
    return (text ? await res.text() : await res.json()) as T;
  }

  override async config(): Promise<Config> {
    const c = await this.req<{ mode: "header" | "token"; header: string; source: { kind: "databricks" | "postgres"; catalog: string | null }; materialization?: string }>("GET", "/auth/config");
    this.cfg = { sourceKind: c.source.kind, catalog: c.source.catalog, authMode: c.mode, authHeader: c.header, materialization: c.materialization ?? "none" };
    return this.cfg;
  }
  override async me(): Promise<Me> { const m = await this.req<{ name: string; role: Role }>("GET", "/me"); return { name: m.name, role: m.role }; }

  private toVersion(d: BackendDomain, v: BackendVersion): VersionInfo {
    this.versionIds[`${d.name}:${v.version}`] = v.id;
    const parts = [v.has_ontology ? "ontology" : "no ontology", v.has_mapping ? "mapping" : "no mapping", `${v.rule_count} rules`, `${v.constraint_count} constraints`];
    return { id: v.id, version: v.version, status: v.status, content: parts.join(" · "), mappingPct: null, lastBuild: "—", active: d.active_version_id === v.id, created: v.created_at ?? "", by: v.created_by ?? "", stats: { classes: 0, attrs: 0, rels: 0, bindings: 0, rules: v.rule_count, constraints: v.constraint_count, triples: 0 }, lease: v.lease ? { holder: v.lease.holder, expires: v.lease.expires_at } : null, review: null, changes: [] };
  }
  private async toDomain(d: BackendDomain, card?: BackendCard): Promise<DomainSummary> {
    const vs = await this.req<BackendVersion[]>("GET", `/domains/${encodeURIComponent(d.name)}/versions`);
    const cfg = this.cfg ?? await this.config();
    const versions = vs.map(v => this.toVersion(d, v)).sort((a, b) => b.version - a.version);
    const c = card ?? (await this.req<BackendCard[]>("GET", "/domains/cards")).find(x => x.name === d.name);
    return { name: d.name, description: d.description ?? "", base_iri: d.base_iri, quorum: d.review_quorum, schema: c?.source.schema ?? d.default_schema ?? "", catalog: c?.source.catalog ?? d.default_catalog ?? cfg.catalog ?? d.name,
      materialization: d.materialization ?? cfg.materialization, target: d.target_schema ?? "", mcpExposed: c?.mcp.exposed ?? d.mcp_policy?.exposed ?? true, disabledTools: c?.mcp.disabled_tools ?? d.mcp_policy?.disabled_tools ?? [],
      triples: c ? c.triples.toLocaleString() : "—", lastBuild: c?.last_build ? `${c.last_build.status}${c.last_build.finished_at ? " · " + new Date(c.last_build.finished_at).toLocaleString() : ""}` : "never",
      versions, lease: versions.find(v => v.lease)?.lease ?? null, review: null, connectionId: d.connection_id ?? null, aiConnectionId: d.ai_connection_id ?? null, targetSchema: d.target_schema ?? null };
  }
  override async domains(): Promise<DomainSummary[]> {
    const [ds, cards] = await Promise.all([this.req<BackendDomain[]>("GET", "/domains"), this.req<BackendCard[]>("GET", "/domains/cards")]);
    return Promise.all(ds.map(d => this.toDomain(d, cards.find(c => c.name === d.name))));
  }
  override async updateDomain(domain: string, patch: DomainSettingsPatch): Promise<DomainSummary> { await this.req("PUT", `/domains/${encodeURIComponent(domain)}`, patch); return this.domain(domain); }
  override async sourceFacts(domain: string): Promise<SourceFacts> { return this.req<SourceFacts>("GET", `/domains/${encodeURIComponent(domain)}/source`); }
  override async connectors(): Promise<ConnectorSpec[]> { return this.req<ConnectorSpec[]>("GET", "/connectors"); }
  override async connections(): Promise<ConnectionRec[]> { return this.req<ConnectionRec[]>("GET", "/connections"); }
  override async createConnection(input: ConnectionInput): Promise<ConnectionRec> { return this.req<ConnectionRec>("POST", "/connections", input); }
  override async updateConnection(id: string, input: Partial<ConnectionInput>): Promise<ConnectionRec> { return this.req<ConnectionRec>("PUT", `/connections/${id}`, input); }
  override async deleteConnection(id: string): Promise<void> { await this.req("DELETE", `/connections/${id}`); }
  override async testConnectionDraft(input: Omit<ConnectionInput, "name">): Promise<ConnResult> { return this.req<ConnResult>("POST", "/connections/test", input); }
  override async testConnectionById(id: string): Promise<ConnResult> { return this.req<ConnResult>("POST", `/connections/${id}/test`); }
  override async domain(name: string): Promise<DomainSummary> { return this.toDomain(await this.req<BackendDomain>("GET", `/domains/${encodeURIComponent(name)}`)); }
  override async createDomain(input: NewDomainInput): Promise<DomainSummary> {
    return this.toDomain(await this.req<BackendDomain>("POST", "/domains", { name: input.name, description: input.description, base_iri: input.base_iri, review_quorum: input.quorum }));
  }
  private vid(domain: string, version: number): string {
    const id = this.versionIds[`${domain}:${version}`];
    if (!id) throw new Error(`Version v${version} of ${domain} is not loaded yet`);
    return id;
  }
  override async transition(domain: string, version: number, to: VersionStatus | "active"): Promise<DomainSummary> {
    if (to === "active") await this.req("POST", `/domains/${encodeURIComponent(domain)}/active`, { version_id: this.vid(domain, version) });
    else await this.req("POST", `/versions/${this.vid(domain, version)}/transition`, { to });
    return this.domain(domain);
  }
  override async createDraft(domain: string): Promise<DomainSummary> { await this.req("POST", `/domains/${encodeURIComponent(domain)}/versions`); return this.domain(domain); }
  override async audit(domain: string): Promise<AuditEntry[]> {
    const d = await this.domain(domain); const latest = d.versions[0]; if (!latest) return [];
    const rows = await this.req<{ actor: string; action: string; at: string }[]>("GET", `/versions/${this.vid(domain, latest.version)}/audit`);
    return rows.map(r => ({ who: r.actor, what: r.action, version: latest.version, when: r.at }));
  }
  override async comments(domain: string): Promise<Comment[]> {
    const d = await this.domain(domain); const latest = d.versions[0]; if (!latest) return [];
    const rows = await this.req<{ author: string; created_at: string; body: string }[]>("GET", `/versions/${this.vid(domain, latest.version)}/comments`);
    return rows.map(r => ({ who: r.author, when: r.created_at, text: r.body }));
  }
  override async addComment(domain: string, text: string): Promise<Comment[]> {
    const d = await this.domain(domain); const latest = d.versions[0]; if (!latest) return [];
    await this.req("POST", `/versions/${this.vid(domain, latest.version)}/comments`, { body: text });
    return this.comments(domain);
  }
  override async setMcp(domain: string, exposed: boolean): Promise<void> { await this.req("PUT", `/domains/${encodeURIComponent(domain)}/mcp-policy`, { exposed, disabled_tools: [] }); }

  override async catalogTables(_domain: string, schema: string): Promise<CatalogTable[]> {
    const names = await this.req<string[]>("GET", `/catalog/tables?schema_name=${encodeURIComponent(schema)}`);
    return names.map(n => ({ name: n.split(".").pop() ?? n, cols: 0, imported: false, cls: null }));
  }
  override async tableDetail(_domain: string, schema: string, table: string): Promise<TableDetail> {
    const cfg = this.cfg ?? await this.config();
    const full = cfg.sourceKind === "databricks" && cfg.catalog ? tableName("databricks", cfg.catalog, schema, table) : `${schema}.${table}`;
    const t = await this.req<{ comment: string | null; columns: { name: string; type: string; comment: string | null }[]; primary_key: string[]; foreign_keys: { columns: string[] }[] }>("GET", `/catalog/tables/${encodeURIComponent(full)}`);
    const pk = new Set(t.primary_key ?? []); const fk = new Set((t.foreign_keys ?? []).flatMap(f => f.columns));
    return { name: table, fullName: full, comment: t.comment ?? "", columns: t.columns.map(c => ({ name: c.name, type: c.type, comment: c.comment ?? "", key: pk.has(c.name) ? "pk" : fk.has(c.name) ? "fk" : null, keyInferred: false })) };
  }
  override async ontology(domain: string, version: number): Promise<OntoClass[]> {
    const o = await this.req<{ classes: { iri: string; label: string | null; description: string | null; parents: string[] }[]; object_properties: { iri: string; domain: string | null; domains: string[]; range: string | null }[]; datatype_properties: { iri: string; domain: string | null; domains: string[]; range: string | null }[] }>("GET", `/versions/${this.vid(domain, version)}/ontology`);
    const local = (iri: string) => iri.split(/[#/]/).pop() ?? iri;
    const doms = (p: { domain: string | null; domains: string[] }) => (p.domains?.length ? p.domains : p.domain ? [p.domain] : []);
    const n = o.classes.length || 1;
    return o.classes.map((c, i) => ({
      id: local(c.iri), iri: c.iri, x: 12 + (i % 4) * 25 + ((i >> 2) % 2) * 8, y: 14 + Math.floor(i / 4) * (72 / Math.max(1, Math.ceil(n / 4) - 1 || 1)),
      desc: c.description ?? "", parents: c.parents.map(local),
      attrs: o.datatype_properties.filter(p => doms(p).includes(c.iri)).map(p => ({ name: local(p.iri), range: p.range ? `xsd:${local(p.range)}` : "" })),
      rels: o.object_properties.filter(p => doms(p).includes(c.iri) && p.range).map(p => ({ name: local(p.iri), target: local(p.range as string) })),
    }));
  }
  override async mapping(domain: string, version: number): Promise<Record<string, ClassMapping>> {
    const st = await this.req<{ classes: { class_iri: string; state: "complete" | "partial" | "unmapped" }[] }>("GET", `/versions/${this.vid(domain, version)}/mapping/status`);
    const spec = await this.req<{ classes?: { class_iri: string; table: string | null; sql_query: string | null; key_columns: string[]; attributes: { property_iri: string; column: string }[] }[] }>("GET", `/versions/${this.vid(domain, version)}/mapping`);
    const local = (iri: string) => iri.split(/[#/]/).pop() ?? iri;
    const out: Record<string, ClassMapping> = {};
    for (const c of spec.classes ?? []) {
      const parts = (c.table ?? "").split(".");
      out[local(c.class_iri)] = { table: c.table ? [parts.length > 1 ? parts[parts.length - 2] : "", parts[parts.length - 1]] : undefined, sql: c.sql_query ?? undefined, key: c.key_columns[0] ?? "", state: st.classes.find(s => s.class_iri === c.class_iri)?.state ?? "partial", cols: Object.fromEntries(c.attributes.map(a => [local(a.property_iri), a.column])) };
    }
    return out;
  }
  override async tablePreview(domain: string, cls: string): Promise<TablePreview> {
    const d = await this.domain(domain); const v = d.versions[0]; const m = (await this.mapping(domain, v.version))[cls];
    if (!m?.table) return { columns: [], rows: [] };
    const r = await this.req<{ columns: string[]; rows: Record<string, string | null>[] }>("GET", `/versions/${this.vid(domain, v.version)}/mapping/table-preview?table=${encodeURIComponent(m.table.join("."))}&limit=5`);
    return { columns: r.columns, rows: r.rows.map(row => r.columns.map(c => row[c])) };
  }
  override async classSql(domain: string, cls: string): Promise<string> {
    const d = await this.domain(domain); const v = d.versions[0]; const cfg = this.cfg ?? await this.config();
    return this.req<string>("GET", `/versions/${this.vid(domain, v.version)}/mapping/sql?dialect=${cfg.sourceKind}&class_iri=${encodeURIComponent(`${d.base_iri.replace(/\/$/, "")}#${cls}`)}`, undefined, true);
  }

  private toRun(r: { id: string; status: BuildRun["status"]; actor: string | null; started_at: string; finished_at: string | null; triple_count: number | null; error: string | null; steps: { name: string; seconds: number; detail?: Record<string, unknown> }[] }): BuildRun {
    const secs = r.finished_at ? (new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) / 1000 : null;
    const running = r.status === "running" || r.status === "queued";
    return { id: `#${r.id.slice(0, 4)}`, status: r.status, actor: r.actor ?? "", duration: secs != null ? `${secs.toFixed(1)} s` : "—", triples: r.triple_count?.toLocaleString() ?? "—", inferred: "—", error: r.error ?? "", stepIndex: running ? r.steps.length : -1,
      steps: r.steps.map(s => ({ name: s.name, detail: s.detail ? Object.entries(s.detail).map(([k, v]) => `${v} ${k}`).join(", ") : "", seconds: s.seconds, state: "done" })) };
  }
  override async builds(domain: string, version: number): Promise<BuildRun[]> { const rs = await this.req<Parameters<RestApi["toRun"]>[0][]>("GET", `/versions/${this.vid(domain, version)}/builds`); return rs.map(r => this.toRun(r)); }
  override async startBuild(domain: string, version: number): Promise<BuildRun> { return this.toRun(await this.req("POST", `/versions/${this.vid(domain, version)}/builds`)); }
  override async buildStatus(runId: string): Promise<BuildRun> { return this.toRun(await this.req("GET", `/builds/${runId.replace(/^#/, "")}`)); }
  override async cancelBuild(runId: string): Promise<BuildRun> { return this.toRun(await this.req("POST", `/builds/${runId.replace(/^#/, "")}/cancel`)); }

  private async activeVid(domain: string): Promise<string> { const d = await this.domain(domain); const v = d.versions.find(x => x.active) ?? d.versions[0]; return this.vid(domain, v.version); }
  override async search(domain: string, q: string): Promise<SearchHit[]> {
    const hits = await this.req<{ iri: string; label: string; types: string[] }[]>("GET", `/versions/${await this.activeVid(domain)}/graph/search?q=${encodeURIComponent(q)}&limit=20`);
    return hits.map(h => ({ id: h.iri, label: h.label, type: (h.types[0] ?? "").split(/[#/]/).pop() ?? "" }));
  }
  override async entity(domain: string, id: string): Promise<EntityDetail> {
    const e = await this.req<{ iri: string; label: string; types: string[]; attributes: { predicate: string; value: string; datatype: string | null; inferred: boolean }[]; outgoing: { predicate: string; target: string; inferred: boolean }[]; incoming: { predicate: string; source: string; inferred: boolean }[] }>("GET", `/versions/${await this.activeVid(domain)}/graph/entity?iri=${encodeURIComponent(id)}`);
    const local = (iri: string) => iri.split(/[#/]/).pop() ?? iri;
    const group = <T extends { predicate: string }>(xs: T[], pick: (x: T) => string) => Object.entries(xs.reduce<Record<string, string[]>>((acc, x) => { (acc[x.predicate] ||= []).push(pick(x)); return acc; }, {}));
    return { id: e.iri, label: e.label, type: local(e.types[0] ?? ""), iri: e.iri,
      attrs: e.attributes.map(a => ({ k: local(a.predicate), v: a.value, dt: a.datatype ? `xsd:${local(a.datatype)}` : "", inferred: a.inferred })),
      out: group(e.outgoing, x => x.target).map(([pred, ts]) => ({ pred: local(pred), targets: ts.map(t => ({ id: t, label: local(t), type: "" })) })),
      inc: group(e.incoming, x => x.source).map(([pred, ts]) => ({ pred: local(pred), count: `${ts.length}`, targets: ts.slice(0, 20).map(t => ({ id: t, label: local(t), type: "" })) })), far: [] };
  }
  override async graphStatus(domain: string): Promise<GraphStatus> {
    const s = await this.req<{ triples: number; inferred: number; entities?: number }>("GET", `/versions/${await this.activeVid(domain)}/graph/status`);
    return { triples: s.triples.toLocaleString(), inferred: s.inferred.toLocaleString(), entities: (s.entities ?? 0).toLocaleString() };
  }
  override async triples(domain: string, q: TripleQuery): Promise<TriplePage> {
    const inferred = q.filter === "all" ? "" : `&inferred=${q.filter === "inferred"}`;
    const p = await this.req<{ total: number; rows: { subject: string; predicate: string; object: string; object_type: string; datatype: string | null; inferred: boolean }[] }>("GET", `/versions/${await this.activeVid(domain)}/graph/triples?text=${encodeURIComponent(q.q)}${inferred}&sort=${q.sort}&direction=${q.dir}&limit=${q.limit}&offset=${q.offset}`);
    return { total: p.total.toLocaleString(), rows: p.rows.map(r => ({ s: r.subject, p: r.predicate, o: r.object, isIri: r.object_type === "iri", dt: r.datatype ? `xsd:${r.datatype.split("#").pop()}` : "", inferred: r.inferred })) };
  }
  override async testConnection(): Promise<ConnResult> {
    const t0 = performance.now();
    try { const names = await this.req<string[]>("GET", "/catalog/tables"); return { ok: true, title: "Connected", detail: `GET /catalog/tables → ${names.length} tables in ${Math.round(performance.now() - t0).toLocaleString()} ms` }; }
    catch (e) { const msg = e instanceof Error ? e.message : String(e); return { ok: false, title: msg.includes("PERMISSION") ? "Permission error" : "Connection failed", detail: msg, action: msg.includes("PERMISSION") ? "Ask the workspace admin for USE CATALOG / USE SCHEMA / SELECT on the catalog for the service principal." : undefined }; }
  }
  override async principals(): Promise<Principal[]> { const ps = await this.req<{ name: string; role: Role }[]>("GET", "/admin/principals"); return ps.map(p => ({ name: p.name, role: p.role, seen: "—" })); }
}
