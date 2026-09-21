// REST adapter for the datagraph backend (FastAPI, docs/UI-BLUEPRINT.html §8).
// Methods with a settled contract call the API; the rest fall through to the mock so the
// app stays usable while integration proceeds. Replace fallbacks method by method.
import { MockApi } from "./mock";
import type { AiProgress, AuditEntry, BuildRun, GraphSample, SearchOptions, BuildStep, CatalogTable, ChecklistItem, DqColumnIssue, DriftIssue, GlossaryTerm, MappingKpis, OntoDiff, TableProfile, ClassMapping, Comment, Config, ConnResult, ConnectionRec, ConnectorSpec, DomainSettingsPatch, DomainSummary, EntityDetail, GraphStatus, Me, NewDomainInput, OntoClass, Principal, Role, SearchHit, RefreshChange, SnapshotTable, SourceFacts, TableDetail, TablePreview, Task, TriplePage, TripleQuery, VersionInfo, VersionStatus } from "./types";
import { tableName } from "./types";
import { humanAction, relTime } from "./format";

export class ApiError extends Error {
  constructor(public status: number, public detail: string) { super(detail); }
}

export interface RestOptions { base?: string; actor?: string; token?: string; pollMs?: number }

interface BackendVersion { id: string; version: number; status: VersionStatus; has_ontology: boolean; has_mapping: boolean; rule_count: number; constraint_count: number; created_at?: string; updated_at?: string; editor?: string | null; lease_expires_at?: string | null }
interface BackendStats { classes: number; attributes: number; relationships: number; bindings: number; rules: number; constraints: number; triples: number }
interface BackendSummary extends BackendVersion {
  created_by: string | null; is_active: boolean; stats: BackendStats;
  mapping: { completion: number; classes_mapped: number; classes: number; complete_classes: number } | null;
  last_build: { id: string; status: string; started_at: string; finished_at: string | null; triple_count: number | null; error: string | null } | null;
  review: { quorum: number; round: number; approved: number; rejected: number; rows: { reviewer: string; approved: boolean; comment: string | null; at: string }[] } | null;
  lease: { holder: string; expires_at: string | null; expired: boolean } | null;
}
interface BackendDomain { name: string; description: string | null; base_iri: string; review_quorum: number; active_version_id?: string | null; connection_id?: string | null; ai_connection_id?: string | null; default_catalog?: string | null; default_schema?: string | null; schemas?: string[]; sources?: { connection_id: string | null; catalog: string | null; schemas: string[] }[]; materialization?: string; target_schema?: string | null; mcp_policy?: { exposed?: boolean; disabled_tools?: string[] } }
interface AiJob<T> { id: string; status: "running" | "succeeded" | "failed"; progress: string | null; started_at: string | null; progress_at: string | null; result: T | null; error: string | null }
interface BackendSpec { base_iri: string; classes: { class_iri: string; table: string | null; sql_query: string | null; key_columns: string[]; iri_template: string | null; attributes: { property_iri: string; column: string; datatype: string | null; language: string | null }[]; excluded: string[] }[]; relations: { property_iri: string; source_class: string; target_class: string; source_key: string[] | null; target_key: string[] | null; table: string | null; sql_query: string | null; direction: string }[] }
interface BackendCard { name: string; version_count: number; active_version: { version: number } | null; latest_version: { version: number; status: string } | null; triples: number; last_build: { status: string; finished_at: string | null; triple_count: number | null } | null; source: { kind: string; connection: string | null; catalog: string | null; schema: string | null }; mcp: { exposed: boolean; disabled_tools: string[] } }

export class RestApi extends MockApi {
  private base: string;
  private ropts: RestOptions;
  private versionIds: Record<string, string> = {};   // "domain:3" -> uuid
  private materializations: Record<string, string> = {};   // domain -> none | view | table (decides whether a build publishes)
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
    this.cfg = { sourceKind: c.source.kind, catalog: c.source.catalog, authMode: c.mode, authHeader: c.header, materialization: c.materialization ?? "none", capabilities: { profiling: false, quality: false, glossary: false, ontoDiffs: false } };
    return this.cfg;
  }
  override async me(): Promise<Me> { const m = await this.req<{ name: string; role: Role }>("GET", "/me"); return { name: m.name, role: m.role }; }

  private toVersion(d: BackendDomain, v: BackendSummary, prev?: BackendSummary): VersionInfo {
    this.versionIds[`${d.name}:${v.version}`] = v.id;
    const pct = v.mapping ? Math.round(v.mapping.completion * 100) : null;
    const n = (k: number, one: string, many = one + "s") => `${k} ${k === 1 ? one : many}`;
    const parts = [v.has_ontology ? "ontology" : "no ontology", pct == null ? "no mapping" : `mapping ${pct}%`, n(v.stats.rules, "rule"), n(v.stats.constraints, "constraint")];
    const changes: VersionInfo["changes"] = [];
    if (prev) for (const [k, one, many] of [["classes", "class", "classes"], ["attributes", "attribute"], ["relationships", "relationship"], ["bindings", "mapped binding"], ["rules", "rule"], ["constraints", "constraint"]] as [keyof BackendStats, string, string?][]) {
      const delta = v.stats[k] - prev.stats[k];
      if (delta) changes.push({ sign: delta > 0 ? "+" : "-", text: n(Math.abs(delta), one, many) });
    }
    const b = v.last_build;
    return { id: v.id, version: v.version, status: v.status, content: parts.join(" · "), mappingPct: pct,
      lastBuild: b ? `${b.status} · ${relTime(b.finished_at ?? b.started_at)}` : "never", active: v.is_active,
      created: relTime(v.created_at), by: v.created_by ?? "", 
      stats: { classes: v.stats.classes, attrs: v.stats.attributes, rels: v.stats.relationships, bindings: v.stats.bindings, rules: v.stats.rules, constraints: v.stats.constraints, triples: v.stats.triples },
      lease: v.lease ? { holder: v.lease.holder, expires: v.lease.expired ? "expired" : relTime(v.lease.expires_at).replace(/^in /, ""), expiresAt: v.lease.expires_at, expired: v.lease.expired } : null,
      review: v.review ? { approved: v.review.approved, rejected: v.review.rejected, quorum: v.review.quorum, round: v.review.round, rows: v.review.rows.map(r => ({ who: r.reviewer, note: r.comment ?? "", state: r.approved ? "approved" : "rejected", when: relTime(r.at) })) } : null,
      changes };
  }
  private async toDomain(d: BackendDomain, card?: BackendCard): Promise<DomainSummary> {
    const vs = (await this.req<BackendSummary[]>("GET", `/domains/${encodeURIComponent(d.name)}/versions/summary`)).sort((a, b) => b.version - a.version);
    const cfg = this.cfg ?? await this.config();
    const versions = vs.map((v, i) => this.toVersion(d, v, vs[i + 1]));
    const c = card ?? (await this.req<BackendCard[]>("GET", "/domains/cards")).find(x => x.name === d.name);
    this.materializations[d.name] = d.materialization ?? cfg.materialization;
    return { name: d.name, description: d.description ?? "", base_iri: d.base_iri, quorum: d.review_quorum, schema: d.schemas?.[0] ?? c?.source.schema ?? d.default_schema ?? "", schemas: d.schemas ?? (d.default_schema ? [d.default_schema] : []), sources: (d.sources ?? []).map(x => ({ connectionId: x.connection_id ?? null, catalog: x.catalog ?? null, schemas: [...(x.schemas ?? [])] })), catalog: c?.source.catalog ?? d.default_catalog ?? cfg.catalog ?? d.name,
      materialization: d.materialization ?? cfg.materialization, target: d.target_schema ?? "", mcpExposed: c?.mcp.exposed ?? d.mcp_policy?.exposed ?? true, disabledTools: c?.mcp.disabled_tools ?? d.mcp_policy?.disabled_tools ?? [],
      triples: c ? c.triples.toLocaleString() : "—", lastBuild: c?.last_build ? `${c.last_build.status}${c.last_build.finished_at ? " · " + new Date(c.last_build.finished_at).toLocaleString() : ""}` : "never",
      versions, lease: versions.find(v => v.status === "draft")?.lease ?? null, review: versions.find(v => v.status === "in_review")?.review ?? null, connectionId: d.connection_id ?? null, aiConnectionId: d.ai_connection_id ?? null, targetSchema: d.target_schema ?? null };
  }
  override async domains(): Promise<DomainSummary[]> {
    const [ds, cards] = await Promise.all([this.req<BackendDomain[]>("GET", "/domains"), this.req<BackendCard[]>("GET", "/domains/cards")]);
    return Promise.all(ds.map(d => this.toDomain(d, cards.find(c => c.name === d.name))));
  }
  override async updateDomain(domain: string, patch: DomainSettingsPatch): Promise<DomainSummary> { await this.req("PUT", `/domains/${encodeURIComponent(domain)}`, patch); return this.domain(domain); }
  override async sourceFacts(domain: string): Promise<SourceFacts> { return this.req<SourceFacts>("GET", `/domains/${encodeURIComponent(domain)}/source`); }
  override async connectors(): Promise<ConnectorSpec[]> { return this.req<ConnectorSpec[]>("GET", "/connectors"); }
  override async connections(): Promise<ConnectionRec[]> { return this.req<ConnectionRec[]>("GET", "/connections"); }
  override async testConnectionById(id: string): Promise<ConnResult> { return this.req<ConnResult>("POST", `/connections/${id}/test`); }
  override async detachConnection(id: string): Promise<void> { await this.req("DELETE", `/connections/${id}/references`); }
  override async domain(name: string): Promise<DomainSummary> { return this.toDomain(await this.req<BackendDomain>("GET", `/domains/${encodeURIComponent(name)}`)); }
  override async createDomain(input: NewDomainInput): Promise<DomainSummary> {
    const body: Record<string, unknown> = { name: input.name, description: input.description, base_iri: input.base_iri, review_quorum: input.quorum };
    if (input.ai_connection_id) body.ai_connection_id = input.ai_connection_id;
    if (input.sources?.length) body.sources = input.sources;
    return this.toDomain(await this.req<BackendDomain>("POST", "/domains", body));
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
  override async review(domain: string, version: number, approved: boolean, comment?: string): Promise<DomainSummary> {
    await this.req("POST", `/versions/${this.vid(domain, version)}/reviews`, { approved, comment: comment ?? null });
    if (!approved) await this.req("POST", `/versions/${this.vid(domain, version)}/transition`, { to: "draft" });
    return this.domain(domain);
  }
  override async takeLease(domain: string, version: number, force = false): Promise<DomainSummary> {
    await this.req("POST", `/versions/${this.vid(domain, version)}/lease`, { ttl_seconds: 900, force });
    return this.domain(domain);
  }
  override async releaseLease(domain: string, version: number): Promise<DomainSummary> {
    await this.req("DELETE", `/versions/${this.vid(domain, version)}/lease`);
    return this.domain(domain);
  }
  override async deleteDraft(domain: string, version: number): Promise<DomainSummary> {
    await this.req("DELETE", `/versions/${this.vid(domain, version)}`);
    delete this.versionIds[`${domain}:${version}`];
    return this.domain(domain);
  }
  override async exportBundle(domain: string, version: number): Promise<unknown> {
    return this.req("GET", `/domains/${encodeURIComponent(domain)}/export?version_id=${this.vid(domain, version)}`);
  }
  override async tasks(): Promise<Task[]> {
    type T = { domain: string; version_id: string; version: number; status: VersionStatus; editor: string | null; approvals: number; quorum: number };
    const t = await this.req<{ drafts: T[]; to_review: T[]; publishable: T[] }>("GET", "/tasks");
    const me = this.ropts.actor ?? "alice";
    return [
      ...t.to_review.map(x => ({ title: `Review ${x.domain} v${x.version}`, sub: `${x.approvals} of ${x.quorum} approvals · your review is pending`, when: "now", icon: "tasks", go: { screen: "versions", domain: x.domain, version: x.version } })),
      ...t.publishable.map(x => ({ title: `Publish ${x.domain} v${x.version}`, sub: `Quorum met · ${x.approvals} of ${x.quorum} approvals`, when: "now", icon: "check", go: { screen: "versions", domain: x.domain, version: x.version } })),
      ...t.drafts.filter(x => x.editor === me).map(x => ({ title: `Your draft ${x.domain} v${x.version}`, sub: "You hold the edit lease", when: "now", icon: "settings", go: { screen: "overview", domain: x.domain, version: x.version } })),
    ];
  }
  override async audit(domain: string): Promise<AuditEntry[]> {
    const d = await this.domain(domain);
    type Row = { actor: string | null; action: string; created_at: string; detail: Record<string, unknown> | null };
    const trails = await Promise.all(d.versions.map(async v => (await this.req<Row[]>("GET", `/versions/${this.vid(domain, v.version)}/audit`)).map(r => ({ ...r, version: v.version }))));
    return trails.flat().sort((a, b) => b.created_at.localeCompare(a.created_at))
      .map(r => ({ who: r.actor ?? "system", what: humanAction(r.action, r.detail), version: r.version, when: relTime(r.created_at) }));
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

  override async schemas(domain: string): Promise<{ id: string; label: string; group?: string }[]> {
    const f = await this.sourceFacts(domain);
    const entries = f.sources?.length ? f.sources : [{ kind: f.kind, connection: f.connection, catalog: f.catalog, schemas: f.schemas ?? (f.schema ? [f.schema] : []) }];
    const all = async (catalog: string | null) => this.req<string[]>("GET", `/catalog/schemas?domain=${encodeURIComponent(domain)}${catalog ? `&catalog=${encodeURIComponent(catalog)}` : ""}`).catch(() => [] as string[]);
    const expanded = await Promise.all(entries.map(async src => ({ ...src, schemas: src.schemas.length ? src.schemas : await all(src.catalog) })));   // none chosen: every schema the source offers
    return expanded.flatMap(src => { const dbx = src.kind === "databricks" && !!src.catalog;
      return src.schemas.map(sch => ({ id: dbx ? `${src.catalog}.${sch}` : sch, label: `${dbx ? `${src.catalog}.` : ""}${sch}`, group: src.connection ?? "deployment default" })); });
  }
  override async catalogSchemas(domain: string): Promise<string[]> {
    const d = await this.domain(domain); const cfg = this.cfg ?? await this.config();
    const q = cfg.sourceKind === "databricks" && d.catalog ? `&catalog=${encodeURIComponent(d.catalog)}` : "";
    return this.req<string[]>("GET", `/catalog/schemas?domain=${encodeURIComponent(domain)}${q}`);
  }
  /** Class mapped to a table (matched on the qualified name, then on the bare table name). */
  private async classOf(domain: string, version: number | undefined, qualified: string): Promise<string | null> {
    if (version === undefined) return null;
    const m = await this.mapping(domain, version).catch(() => ({} as Record<string, ClassMapping>));
    const q = qualified.toLowerCase(), bare = q.split(".").pop();
    const hit = Object.entries(m).find(([, x]) => x.fullName?.toLowerCase() === q) ?? Object.entries(m).find(([, x]) => x.fullName?.toLowerCase().split(".").pop() === bare);
    return hit?.[0] ?? null;
  }
  override async catalogTables(domain: string, schema: string, version?: number): Promise<CatalogTable[]> {
    const [raw, snap, mapped] = await Promise.all([
      this.req<({ name: string; columns: number; comment: string | null } | string)[]>("GET", `/catalog/tables?domain=${encodeURIComponent(domain)}&schema_name=${encodeURIComponent(schema)}&detail=true`),
      version !== undefined ? this.snapshot(domain, version).catch(() => [] as SnapshotTable[]) : Promise.resolve([] as SnapshotTable[]),
      version !== undefined ? this.mapping(domain, version).catch(() => ({} as Record<string, ClassMapping>)) : Promise.resolve({} as Record<string, ClassMapping>)]);
    const held = new Map(snap.map(t => [t.table.toLowerCase(), t]));
    const byTable = new Map(Object.entries(mapped).filter(([, x]) => x.fullName).map(([cls, x]) => [x.fullName!.toLowerCase(), cls]));
    const rows = raw.map(r => (typeof r === "string" ? { name: r, columns: 0, comment: null } : r));   // an older backend answers with bare names
    return rows.map(r => { const name = r.name.split(".").pop() ?? r.name; const q = `${schema}.${name}`.toLowerCase(); const t = held.get(q) ?? held.get(name.toLowerCase());
      return { name, cols: r.columns || t?.columns || 0, imported: !!t, cls: byTable.get(q) ?? null }; });
  }
  override async tableClass(domain: string, table: string, version?: number): Promise<string | null> { return this.classOf(domain, version, table); }
  // Not offered by this backend yet: the screens hide the affordances (see Config.capabilities) instead of showing design data.
  override async tableProfile(_domain: string, _table: string): Promise<TableProfile> { return { rows: "—", fresh: "—", dup: "—", cols: {} }; }
  override async tableDq(_domain: string, _table: string): Promise<DqColumnIssue[]> { return []; }
  override async glossary(_domain: string): Promise<GlossaryTerm[]> { return []; }
  override async ontoDiffs(_domain: string, _table: string): Promise<OntoDiff[]> { return []; }
  private toSnapshot(t: { table: string; comment: string | null; columns: { name: string }[]; primary_key: string[]; captured_at?: string | null }): SnapshotTable {
    return { table: t.table, columns: t.columns.length, columnNames: t.columns.map(c => c.name), comment: t.comment, primaryKey: t.primary_key ?? [], capturedAt: t.captured_at ?? null };
  }
  override async snapshot(domain: string, version: number): Promise<SnapshotTable[]> {
    return (await this.req<Parameters<RestApi["toSnapshot"]>[0][]>("GET", `/versions/${this.vid(domain, version)}/metadata`)).map(t => this.toSnapshot(t));
  }
  override async importTables(domain: string, version: number, schema: string, tables: string[]): Promise<SnapshotTable[]> {
    return (await this.req<Parameters<RestApi["toSnapshot"]>[0][]>("POST", `/versions/${this.vid(domain, version)}/metadata/import`, { tables, schema_name: schema })).map(t => this.toSnapshot(t));
  }
  override async refreshSnapshot(domain: string, version: number): Promise<RefreshChange[]> {
    return this.req<RefreshChange[]>("POST", `/versions/${this.vid(domain, version)}/metadata/refresh`);
  }
  override async tableDetail(domain: string, schema: string, table: string): Promise<TableDetail> {
    const cfg = this.cfg ?? await this.config();
    const full = schema.includes(".") ? `${schema}.${table}` : cfg.sourceKind === "databricks" && cfg.catalog ? tableName("databricks", cfg.catalog, schema, table) : `${schema}.${table}`;
    const t = await this.req<{ comment: string | null; columns: { name: string; type: string; comment: string | null }[]; primary_key: string[]; foreign_keys: { columns: string[] }[] }>("GET", `/catalog/tables/${encodeURIComponent(full)}?domain=${encodeURIComponent(domain)}`);
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
  // -- mapping editor: local names <-> IRIs through the version's ontology, edits through the spec --------
  private local(iri: string): string { return iri.split(/[#/]/).pop() ?? iri; }
  private async names(domain: string, version: number) {
    const o = await this.req<{ classes: { iri: string }[]; datatype_properties: { iri: string; domains: string[]; domain: string | null }[]; object_properties: { iri: string; domains: string[]; domain: string | null; range: string | null }[] }>("GET", `/versions/${this.vid(domain, version)}/ontology`);
    const cls = Object.fromEntries(o.classes.map(c => [this.local(c.iri), c.iri]));
    const prop = Object.fromEntries([...o.datatype_properties, ...o.object_properties].map(p => [this.local(p.iri), p.iri]));
    const target = Object.fromEntries(o.object_properties.map(p => [this.local(p.iri), p.range ?? ""]));
    return { cls, prop, target };
  }
  private async spec(domain: string, version: number): Promise<BackendSpec> {
    const raw = await this.req<Partial<BackendSpec>>("GET", `/versions/${this.vid(domain, version)}/mapping`);
    if (!raw.base_iri) { const d = await this.req<BackendDomain>("GET", `/domains/${encodeURIComponent(domain)}`); return { base_iri: d.base_iri, classes: [], relations: [] }; }
    return { base_iri: raw.base_iri, classes: raw.classes ?? [], relations: raw.relations ?? [] };
  }
  private async saveSpec(domain: string, version: number, spec: BackendSpec): Promise<void> { await this.req("PUT", `/versions/${this.vid(domain, version)}/mapping`, spec); }
  private async classEntry(domain: string, version: number, cls: string): Promise<{ spec: BackendSpec; entry: BackendSpec["classes"][number]; names: Awaited<ReturnType<RestApi["names"]>> }> {
    const [spec, names] = await Promise.all([this.spec(domain, version), this.names(domain, version)]);
    const iri = names.cls[cls]; if (!iri) throw new Error(`Class ${cls} is not in the ontology`);
    const entry = spec.classes.find(c => c.class_iri === iri); if (!entry) throw new Error(`${cls} is not mapped to a table yet`);
    return { spec, entry, names };
  }
  /** Follows a background job, relaying each new status, until it settles. */
  private async followJob<T>(job: AiJob<T>, onProgress?: (p: AiProgress) => void): Promise<AiJob<T>> {
    let last = "";
    const relay = (j: AiJob<T>) => { if (j.status === "running" && j.progress && j.progress !== last) { last = j.progress; onProgress?.({ progress: j.progress, startedAt: j.started_at, progressAt: j.progress_at, status: "running" }); } };
    const wait = (ms: number) => new Promise(r => setTimeout(r, ms));
    relay(job);
    while (job.status === "running") {
      await wait(this.ropts.pollMs ?? 2000);
      job = await this.req<AiJob<T>>("GET", `/jobs/${job.id}`);
      relay(job);
    }
    return job;
  }
  /** Starts a long AI task in the background and follows its job to the result (or the error). */
  private async aiJob<T>(path: string, body: unknown, onProgress?: (p: AiProgress) => void): Promise<T> {
    const job = await this.followJob(await this.req<AiJob<T>>("POST", `${path}?background=true`, body), onProgress);
    if (job.status === "failed") throw new Error(job.error ?? "The AI task failed");
    return job.result as T;
  }
  override async suggestRelations(domain: string, version: number, onProgress?: (p: AiProgress) => void) {
    const r = await this.aiJob<{ added: number; declared: number; by_name: number; ai: number; skipped?: string[]; unmappable?: string[] }>(`/versions/${this.vid(domain, version)}/llm/suggest-relations`, {}, onProgress);
    return { added: r.added, declared: r.declared, byName: r.by_name, ai: r.ai, skipped: r.skipped ?? [], unmappable: r.unmappable ?? [] };
  }
  override async runningAiJob(domain: string, version: number, kind: "suggest-mapping" | "draft-ontology" | "suggest-relations", onProgress?: (p: AiProgress) => void): Promise<AiProgress | null> {
    const latest = await this.req<AiJob<unknown> | null>("GET", `/versions/${this.vid(domain, version)}/jobs?kind=${kind}`);
    if (!latest || latest.status !== "running") return null;
    const job = await this.followJob(latest, onProgress);
    return { progress: job.status === "failed" ? (job.error ?? "failed") : (job.progress ?? "Done"), startedAt: job.started_at, progressAt: job.progress_at, status: job.status };
  }
  override async draftOntology(domain: string, version: number, opts: { ai: boolean; description?: string; tables?: string[] }, onProgress?: (p: AiProgress) => void): Promise<{ classes: number; properties: number; warnings: number }> {
    const d = await this.domain(domain); const vid = this.vid(domain, version);
    const ontology_iri = `${d.base_iri.replace(/\/$/, "")}/ontology`;
    const tables = opts.tables ?? (await this.snapshot(domain, version)).map(t => t.table);
    if (opts.ai) {
      const r = await this.aiJob<{ classes: number; properties: number; issues: { severity: string }[] }>(`/versions/${vid}/llm/draft-ontology`, { ontology_iri, description: opts.description ?? "", tables }, onProgress);
      return { classes: r.classes, properties: r.properties, warnings: (r.issues ?? []).filter(i => i.severity === "warning").length };
    }
    const r = await this.req<{ classes: number; properties: number }>("POST", `/versions/${vid}/autodraft`, { ontology_iri, tables, infer_keys: true });
    return { classes: r.classes, properties: r.properties, warnings: 0 };
  }
  override async mapping(domain: string, version: number): Promise<Record<string, ClassMapping>> {
    const [st, spec] = await Promise.all([this.req<{ classes: { class_iri: string; state: "complete" | "partial" | "unmapped" }[] }>("GET", `/versions/${this.vid(domain, version)}/mapping/status`).catch(() => ({ classes: [] })), this.spec(domain, version)]);
    const out: Record<string, ClassMapping> = {};
    for (const c of spec.classes) {
      const parts = (c.table ?? "").split(".");
      const rels = Object.fromEntries(spec.relations.filter(r => r.source_class === c.class_iri).map(r => [this.local(r.property_iri), `${(r.source_key ?? []).join(",")} → ${this.local(r.target_class)}.${(r.target_key ?? []).join(",")}`]));
      out[this.local(c.class_iri)] = { table: c.table ? [parts.length > 1 ? parts[parts.length - 2] : "", parts[parts.length - 1]] : undefined, fullName: c.table ?? undefined, sql: c.sql_query ?? undefined, key: c.key_columns[0] ?? "",
        state: st.classes.find(x => x.class_iri === c.class_iri)?.state ?? "partial", cols: Object.fromEntries(c.attributes.map(a => [this.local(a.property_iri), a.column])), rels, excluded: (c.excluded ?? []).map(e => this.local(e)) };
    }
    return out;
  }
  override async mapClass(domain: string, version: number, cls: string, table: string, key: string[]): Promise<void> {
    const [spec, names] = await Promise.all([this.spec(domain, version), this.names(domain, version)]);
    const iri = names.cls[cls]; if (!iri) throw new Error(`Class ${cls} is not in the ontology`);
    const old = spec.classes.find(c => c.class_iri === iri);
    const entry = { class_iri: iri, table, sql_query: null, key_columns: key, iri_template: null, attributes: old?.table === table ? old.attributes : [], excluded: old?.excluded ?? [] };
    spec.classes = [...spec.classes.filter(c => c.class_iri !== iri), entry];
    await this.saveSpec(domain, version, spec);
  }
  override async bindAttribute(domain: string, version: number, cls: string, attr: string, column: string | null): Promise<void> {
    const { spec, entry, names } = await this.classEntry(domain, version, cls);
    const piri = names.prop[attr]; if (!piri) throw new Error(`${attr} is not a property of the ontology`);
    entry.attributes = entry.attributes.filter(a => a.property_iri !== piri);
    if (column) entry.attributes.push({ property_iri: piri, column, datatype: null, language: null });
    await this.saveSpec(domain, version, spec);
  }
  override async excludeProperty(domain: string, version: number, cls: string, prop: string, excluded: boolean): Promise<void> {
    const { spec, entry, names } = await this.classEntry(domain, version, cls);
    const piri = names.prop[prop]; if (!piri) throw new Error(`${prop} is not a property of the ontology`);
    const ex = new Set(entry.excluded ?? []); if (excluded) ex.add(piri); else ex.delete(piri); entry.excluded = [...ex].sort();
    if (excluded) entry.attributes = entry.attributes.filter(a => a.property_iri !== piri);
    await this.saveSpec(domain, version, spec);
  }
  override async mapRelation(domain: string, version: number, cls: string, rel: string, sourceKey: string[], targetKey: string[]): Promise<void> {
    const { spec, names } = await this.classEntry(domain, version, cls);
    const piri = names.prop[rel], src = names.cls[cls], tgt = names.target[rel]; if (!piri || !tgt) throw new Error(`${rel} is not a relationship of ${cls}`);
    spec.relations = [...spec.relations.filter(r => !(r.property_iri === piri && r.source_class === src)), { property_iri: piri, source_class: src, target_class: tgt, source_key: sourceKey, target_key: targetKey, table: null, sql_query: null, direction: "forward" }];
    await this.saveSpec(domain, version, spec);
  }
  override async unmapClass(domain: string, version: number, cls: string): Promise<void> {
    const names = await this.names(domain, version); const iri = names.cls[cls]; if (!iri) throw new Error(`Class ${cls} is not in the ontology`);
    await this.req("DELETE", `/versions/${this.vid(domain, version)}/mapping/classes?class_iri=${encodeURIComponent(iri)}`);
  }
  override async excludeUnmapped(domain: string, version: number): Promise<void> { await this.req("POST", `/versions/${this.vid(domain, version)}/mapping/exclude-unmapped`); }
  override async drift(domain: string, version: number): Promise<DriftIssue[]> { return this.req<DriftIssue[]>("GET", `/versions/${this.vid(domain, version)}/mapping/drift`); }
  override async r2rml(domain: string, version: number): Promise<string> { return this.req<string>("GET", `/versions/${this.vid(domain, version)}/mapping/r2rml`, undefined, true); }
  override async suggestMapping(domain: string, version: number, onProgress?: (p: AiProgress) => void): Promise<{ classes: number; relations: number; skipped: string[] }> {
    const r = await this.aiJob<{ classes: number; relations: number; skipped?: string[] }>(`/versions/${this.vid(domain, version)}/llm/suggest-mapping`, {}, onProgress);
    return { classes: r.classes, relations: r.relations, skipped: r.skipped ?? [] };
  }
  override async tablePreview(domain: string, cls: string, version?: number): Promise<TablePreview> {
    const v = version ?? (await this.domain(domain)).versions[0]?.version; if (v === undefined) return { columns: [], rows: [] };
    const m = (await this.mapping(domain, v))[cls];
    if (!m?.fullName) return { columns: [], rows: [] };
    const r = await this.req<{ columns: string[]; rows: Record<string, string | null>[] }>("GET", `/versions/${this.vid(domain, v)}/mapping/table-preview?table=${encodeURIComponent(m.fullName)}&limit=5`);
    return { columns: r.columns, rows: r.rows.map(row => r.columns.map(c => row[c])) };
  }
  override async classSql(domain: string, cls: string, version?: number): Promise<string> {
    const v = version ?? (await this.domain(domain)).versions[0]?.version; if (v === undefined) return "";
    const cfg = this.cfg ?? await this.config(); const names = await this.names(domain, v); const iri = names.cls[cls]; if (!iri) return "";
    return this.req<string>("GET", `/versions/${this.vid(domain, v)}/mapping/sql?dialect=${cfg.sourceKind}&class_iri=${encodeURIComponent(iri)}`, undefined, true);
  }
  /** The pipeline's step order, so a running build shows what is still to come. */
  private pipeline(domain: string): string[] {
    const publish = (this.materializations[domain] ?? "none") !== "none";
    return ["compile", "drift", "prepare", ...(publish ? ["publish"] : []), "load", "finalize"];
  }
  private toRun(r: { id: string; status: BuildRun["status"]; actor: string | null; started_at: string; finished_at: string | null; triple_count: number | null; error: string | null; steps: { name: string; seconds: number | null; detail?: Record<string, unknown> }[] }, domain?: string): BuildRun {
    const secs = r.finished_at ? (new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) / 1000 : null;
    const running = r.status === "running" || r.status === "queued";
    const detail = (d?: Record<string, unknown>) => d ? Object.entries(d).filter(([, v]) => typeof v !== "object" || v === null).map(([k, v]) => `${v} ${k}`).join(", ") + (Array.isArray(d.issues) ? `${d.issues.length} drift issue${d.issues.length === 1 ? "" : "s"}` : "") : "";
    const done = r.steps.map(s => ({ name: s.name, detail: detail(s.detail), seconds: s.seconds, state: (s.seconds == null && running ? "running" : "done") as BuildStep["state"] }));
    const seen = new Set(done.map(s => s.name));
    const queued = running && domain ? this.pipeline(domain).filter(n => !seen.has(n)).map(n => ({ name: n, detail: "", seconds: null, state: "queued" as const })) : [];
    const steps = [...done, ...queued];
    const stepIndex = running ? Math.max(steps.findIndex(s => s.state === "running"), 0) : -1;
    const inferred = r.steps.find(s => s.name === "infer")?.detail?.inferred;
    return { id: r.id, label: `#${r.id.slice(0, 4)}`, status: r.status, actor: r.actor ?? "", duration: secs != null ? `${secs.toFixed(1)} s` : "—", triples: r.triple_count?.toLocaleString() ?? "—", inferred: typeof inferred === "number" ? inferred.toLocaleString() : "—", error: r.error ?? "", stepIndex, steps };
  }
  private runDomains: Record<string, string> = {};   // run id -> domain, so a poll can still show the queued steps
  private remember(domain: string, run: BuildRun): BuildRun { this.runDomains[run.id] = domain; return run; }
  override async builds(domain: string, version: number): Promise<BuildRun[]> { const rs = await this.req<Parameters<RestApi["toRun"]>[0][]>("GET", `/versions/${this.vid(domain, version)}/builds`); return rs.map(r => this.remember(domain, this.toRun(r, domain))); }
  override async startBuild(domain: string, version: number): Promise<BuildRun> { return this.remember(domain, this.toRun(await this.req("POST", `/versions/${this.vid(domain, version)}/builds`), domain)); }
  override async buildStatus(runId: string): Promise<BuildRun> { return this.toRun(await this.req("GET", `/builds/${runId}`), this.runDomains[runId]); }
  override async cancelBuild(runId: string): Promise<BuildRun> { return this.toRun(await this.req("POST", `/builds/${runId}/cancel`), this.runDomains[runId]); }
  override async checklist(domain: string, version: number): Promise<ChecklistItem[]> {
    const vid = this.vid(domain, version);
    const opt = <T,>(path: string) => this.req<T>("GET", path).catch(() => null);
    const [snap, onto, status, checks, drift] = await Promise.all([
      opt<unknown[]>(`/versions/${vid}/metadata`), opt<{ classes: unknown[] }>(`/versions/${vid}/ontology`), opt<{ completion: number }>(`/versions/${vid}/mapping/status`),
      opt<{ severity: string }[]>(`/versions/${vid}/ontology/checks`), opt<unknown[]>(`/versions/${vid}/mapping/drift`)]);
    const n = (k: number, one: string, many = one + "s") => `${k} ${k === 1 ? one : many}`;
    const errors = (checks ?? []).filter(c => c.severity === "error").length;
    const pct = status ? Math.round(status.completion * 100) : null;
    return [
      { label: "Snapshot", value: snap?.length ? n(snap.length, "table") : "no tables imported", ok: !!snap?.length, go: { screen: "metadata" } },
      { label: "Ontology", value: onto?.classes.length ? n(onto.classes.length, "class", "classes") : "none yet", ok: !!onto?.classes.length, go: { screen: "ontology" } },
      { label: "Mapping completion", value: pct == null ? "no mapping" : `${pct}%`, ok: pct === 100, go: { screen: "mapping" } },
      { label: "Ontology checks", value: checks ? n(errors, "error") : "—", ok: !!checks && errors === 0, go: { screen: "ontology", arg: "checks" } },
      { label: "Schema drift", value: n(drift?.length ?? 0, "issue"), ok: !(drift?.length), go: { screen: "metadata" } },
    ];
  }
  override async mappingKpis(domain: string, version: number): Promise<MappingKpis> {
    const st = await this.req<{ completion: number; summary: Record<string, number> }>("GET", `/versions/${this.vid(domain, version)}/mapping/status`).catch(() => null);
    if (!st) return { completion: 0, classesMapped: [0, 0], attributes: [0, 0], relationships: [0, 0], excluded: 0 };
    const s = st.summary;
    return { completion: Math.round(st.completion * 100), classesMapped: [s.mapped_classes, s.classes], attributes: [s.mapped_attributes, s.attributes], relationships: [s.mapped_relations, s.relations], excluded: (s.excluded_attributes ?? 0) + (s.excluded_relations ?? 0) };
  }

  private async activeVid(domain: string): Promise<string> { const d = await this.domain(domain); const v = d.versions.find(x => x.active) ?? d.versions[0]; return this.vid(domain, v.version); }
  override async search(domain: string, q: string, opts?: SearchOptions): Promise<SearchHit[]> {
    const params = new URLSearchParams({ q, limit: "20", match: opts?.match ?? "contains" });
    if (opts?.type) params.set("type", opts.type);
    const hits = await this.req<{ iri: string; label: string; types: string[] }[]>("GET", `/versions/${await this.activeVid(domain)}/graph/search?${params}`);
    return hits.map(h => ({ id: h.iri, label: h.label, type: (h.types[0] ?? "").split(/[#/]/).pop() ?? "" }));
  }
  override async entity(domain: string, id: string): Promise<EntityDetail> {
    const e = await this.req<{ neighbours?: { iri: string; label: string; types: string[] }[]; iri: string; label: string; types: string[]; attributes: { predicate: string; value: string; datatype: string | null; inferred: boolean }[]; outgoing: { predicate: string; target: string; inferred: boolean }[]; incoming: { predicate: string; source: string; inferred: boolean }[] }>("GET", `/versions/${await this.activeVid(domain)}/graph/entity?iri=${encodeURIComponent(id)}`);
    const local = (iri: string) => iri.split(/[#/]/).pop() ?? iri;
    const known = new Map((e.neighbours ?? []).map(n => [n.iri, n]));
    const hit = (iri: string) => { const n = known.get(iri); return { id: iri, label: n?.label || local(iri), type: n?.types?.[0] ? local(n.types[0]) : "" }; };
    const group = <T extends { predicate: string }>(xs: T[], pick: (x: T) => string) => Object.entries(xs.reduce<Record<string, string[]>>((acc, x) => { (acc[x.predicate] ||= []).push(pick(x)); return acc; }, {}));
    return { id: e.iri, label: e.label, type: local(e.types[0] ?? ""), iri: e.iri,
      attrs: e.attributes.map(a => ({ k: local(a.predicate), v: a.value, dt: a.datatype ? `xsd:${local(a.datatype)}` : "", inferred: a.inferred })),
      out: group(e.outgoing, x => x.target).map(([pred, ts]) => ({ pred: local(pred), targets: ts.map(hit) })),
      inc: group(e.incoming, x => x.source).map(([pred, ts]) => ({ pred: local(pred), count: `${ts.length}`, targets: ts.slice(0, 20).map(hit) })), far: [] };
  }
  override async graphOverview(domain: string, limit = 300): Promise<GraphSample> {
    const g = await this.req<{ nodes: { iri: string; label: string; types: string[] }[]; edges: { source: string; predicate: string; target: string }[] }>("GET", `/versions/${await this.activeVid(domain)}/graph/overview?limit=${limit}`);
    const local = (iri: string) => iri.split(/[#/]/).pop() ?? iri;
    return { nodes: g.nodes.map(n => ({ id: n.iri, label: n.label || local(n.iri), type: n.types[0] ? local(n.types[0]) : "" })), edges: g.edges.map(e => ({ from: e.source, to: e.target, label: local(e.predicate) })) };
  }
  override async graphStatus(domain: string): Promise<GraphStatus> {
    const s = await this.req<{ triples: number; inferred: number; types?: Record<string, number> }>("GET", `/versions/${await this.activeVid(domain)}/graph/status`);
    const entities = Object.values(s.types ?? {}).reduce((a, b) => a + b, 0);   // one typed subject per entity
    const types = Object.entries(s.types ?? {}).map(([iri, count]) => ({ name: iri.split(/[#/]/).pop() ?? iri, iri, count })).sort((a, b) => b.count - a.count);
    return { triples: s.triples.toLocaleString(), inferred: s.inferred.toLocaleString(), entities: entities.toLocaleString(), types };
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
