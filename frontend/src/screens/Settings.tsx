import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ConnectionForm, TestReportView, ValidationError, useConnectionTypes, useConnections, useConnectionsClient, useTestConnection, type Connection, type ConnectorSummary } from "@polestar/connections";
import { Button, Card, Dialog, Dot, ErrorNotice, KV, Label, Pill, Skeleton, Spinner, Toggle } from "@/components/ui";
import { Icon } from "@/components/icons";
import { useApp, useLoad } from "@/state/app";
import { useDomain, useGo } from "@/state/domain";
import { CONNECTIONS_URL } from "@/config";
import type { ConnResult, DomainSource } from "@/api";

const KIND_LABEL: Record<string, string> = { postgres: "Postgres", databricks: "Databricks", sqlserver: "SQL Server", mssql: "SQL Server", azure_openai: "Azure OpenAI", azureopenai: "Azure OpenAI" };
const isAiKind = (kind: string, types?: ConnectorSummary[]) => (types?.find(t => t.type === kind)?.category ?? (kind.includes("openai") ? "ai" : "source")) === "ai";

export type SettingsCard = "all" | "connections" | "domain" | "mcp";

/** The domain's settings cards. Standalone it is the old Settings page; embedded (Overview) it renders one card or all of them, with extra cards on the right. */
export function Settings({ embedded = false, only = "all", right }: { embedded?: boolean; only?: SettingsCard; right?: ReactNode } = {}) {
  const show = (c: SettingsCard) => only === c;
  const go = useGo();
  const { api, config, say, can } = useApp();
  const { domain, patch } = useDomain();
  const facts = useLoad(() => api.sourceFacts(domain.name), [domain.name]);
  const conns = useLoad(() => api.connections().catch(() => []), []);
  const specs = useLoad(() => api.connectors().catch(() => []), []);
  const [testing, setTesting] = useState(false);
  const [conn, setConn] = useState<ConnResult | null>(null);
  const [mcp, setMcp] = useState(domain.mcpExposed);
  // domain form
  const [description, setDescription] = useState(domain.description);
  const [quorum, setQuorum] = useState(domain.quorum);
  const [baseIri, setBaseIri] = useState(domain.base_iri);
  const [aiId, setAiId] = useState(domain.aiConnectionId ?? "");
  const [sources, setSources] = useState<DomainSource[]>(domain.sources ?? []);
  const available = useLoad(() => api.catalogSchemas(domain.name).catch(() => [] as string[]), [domain.name]);
  const [mat, setMat] = useState<"none" | "view" | "table">("none");
  const [target, setTarget] = useState("");
  useEffect(() => { setDescription(domain.description); setQuorum(domain.quorum); setBaseIri(domain.base_iri); setAiId(domain.aiConnectionId ?? ""); setSources((domain.sources ?? []).map(x => ({ ...x, schemas: [...x.schemas] }))); }, [domain]);
  useEffect(() => { if (facts.data) { setMat((facts.data.materialization as "none" | "view" | "table") || "none"); setTarget(facts.data.target_schema ?? ""); } }, [facts.data]);

  const isAi = (kind: string) => (specs.data?.find(s => s.kind === kind)?.category ?? (kind.includes("openai") ? "ai" : "source")) === "ai";
  const kindLabel = (k: string) => specs.data?.find(s => s.kind === k)?.label ?? KIND_LABEL[k] ?? k;
  const sourceConns = (conns.data ?? []).filter(c => !isAi(c.kind));
  const ais = (conns.data ?? []).filter(c => isAi(c.kind));
  const aiMissing = ais.length > 0 && !aiId;
  const f = facts.data;
  const describe = (x: { connection: string | null; catalog: string | null; schemas: string[] }) => `${x.connection ?? "deployment default"} · ${x.catalog ?? "—"} · ${x.schemas.length ? x.schemas.join(", ") : "—"}`;
  const factSources = f ? (f.sources?.length ? f.sources : [{ connection: f.connection, catalog: f.catalog, schemas: f.schemas ?? (f.schema ? [f.schema] : []) }]) : [];
  const sourceRows: [string, string][] = f ? [["Kind", f.kind], ...factSources.map((x, i) => [i === 0 ? "Primary source" : `Source ${i + 1}`, describe(x)] as [string, string]), ...(f.host ? [["Host", f.host] as [string, string]] : []), ["Auth mode", `${f.auth_mode} · ${f.auth_header}`], ["Materialization", f.materialization + (f.target_schema ? ` → ${f.target_schema}` : "")], ["AI", f.ai ? `${f.ai.connection ?? f.ai.kind} · ${f.ai.deployment ?? "—"}` : "none"]] : [];
  const editSource = (i: number, patch: Partial<DomainSource>) => setSources(sources.map((x, j) => (j === i ? { ...x, ...patch } : x)));

  const test = async () => {
    if (testing) return; setTesting(true); setConn(null);
    try { setConn(f?.connection_id ? await api.testConnectionById(f.connection_id) : await api.testConnection()); conns.reload(); } catch (e) { setConn({ ok: false, title: "Connection failed", detail: e instanceof Error ? e.message : String(e) }); } finally { setTesting(false); }
  };
  const saveSource = async () => {
    try {
      patch(await api.updateDomain(domain.name, { ...(aiId || ais.length ? { ai_connection_id: aiId || null } : {}), sources: sources.map(x => ({ connection_id: x.connectionId, catalog: x.catalog, schemas: x.schemas })), materialization: mat, target_schema: target || null }));
      facts.reload(); say("Source settings saved");
    } catch (e) { say(e instanceof Error ? e.message : String(e)); }
  };
  const saveDomain = async () => {
    try { patch(await api.updateDomain(domain.name, { description, review_quorum: quorum, base_iri: baseIri })); say("Domain settings saved"); }
    catch (e) { say(e instanceof Error ? e.message : String(e)); }
  };
  const refreshAll = () => { conns.reload(); facts.reload(); };

  return (
    <>
      {!embedded && <div className="page-head"><div><h1>Settings</h1><p>Domain description, what MCP exposes, the source warehouse and AI provider this domain uses, and the connections behind them.</p></div></div>}
      {only === "all" && (
        <div className="grid two">
          <div className="grid">
            <Card>
              <div className="row between" style={{ marginBottom: 6 }}><h2 className="h2">Source</h2><a href="#" className="small" style={{ fontWeight: 600 }} onClick={e => { e.preventDefault(); go("overview", { tab: "connections" }); }}>Configure →</a></div>
              {facts.loading && <Skeleton h={80} />}
              {facts.error && <ErrorNotice error={facts.error} />}
              {sourceRows.map(([k, v]) => <KV key={k} k={k} v={v} />)}
              {f?.missing_connection_id && <div className="notice error" style={{ marginTop: 10 }}>This domain's connection no longer exists; choose another one under Connections.</div>}
            </Card>
            <Card>
              <div className="row between" style={{ marginBottom: 6 }}><h2 className="h2">Domain</h2><a href="#" className="small" style={{ fontWeight: 600 }} onClick={e => { e.preventDefault(); go("overview", { tab: "domain" }); }}>Edit →</a></div>
              <KV k="Description" v={domain.description || "—"} mono={false} /><KV k="Review quorum" v={String(domain.quorum)} /><KV k="Base IRI" v={domain.base_iri} />
              <KV k="Versions" v={`${domain.versions.length} · ${domain.versions.find(v => v.active) ? `v${domain.versions.find(v => v.active)!.version} active` : "none active"}`} />
            </Card>
          </div>
          <div className="grid">
            <Card>
              <div className="row between" style={{ marginBottom: 6 }}><h2 className="h2">MCP policy</h2><a href="#" className="small" style={{ fontWeight: 600 }} onClick={e => { e.preventDefault(); go("overview", { tab: "mcp" }); }}>Edit →</a></div>
              <KV k="Agents" v={domain.mcpExposed ? "exposed · active version answers over MCP and GraphQL" : "hidden from agents"} mono={false} />
              <KV k="Disabled tools" v={domain.disabledTools.length ? domain.disabledTools.join(", ") : "none"} />
            </Card>
            {right}
          </div>
        </div>
      )}
      {only !== "all" && <div className="grid">
        <div className="grid">
          {show("connections") && <Card>
            <div className="row between" style={{ marginBottom: 10 }}><h2 className="h2">Source</h2><Button size="sm" variant="outline" style={{ height: 30 }} onClick={test}>{testing && <Spinner blue />}Test connection</Button></div>
            {facts.loading && <Skeleton h={120} />}
            {facts.error && <ErrorNotice error={facts.error} />}
            {sourceRows.map(([k, v]) => <KV key={k} k={k} v={v} />)}
            {f?.missing_connection_id && <div className="notice error" style={{ marginTop: 10 }}><div className="row" style={{ fontWeight: 700, color: "var(--orange)" }}><Dot color="var(--orange)" size={8} />The attached connection no longer exists in the connection module</div><div className="muted xs" style={{ marginTop: 4 }}>Pick another one below and save.</div></div>}
            {conn && <TestNotice r={conn} />}
            <div style={{ marginTop: 16, display: "grid", gap: 12 }}>
              <div>
                <Label>AI connection</Label>
                <select id="ai-conn" aria-label="AI connection" className="select full" value={aiId} onChange={e => setAiId(e.target.value)} aria-invalid={aiMissing}><option value="">None</option>{ais.map(c => <option key={c.id} value={c.id}>{c.name} · {String(c.config.deployment ?? "")}</option>)}</select>
                {aiMissing && <div className="xs" style={{ marginTop: 4, color: "var(--orange-text)", fontWeight: 600 }}>An AI connection is required for every domain: it drafts the ontology and answers Ask.</div>}
              </div>
              <div>
                <div className="row between" style={{ marginBottom: 6 }}><Label block={false}>Sources</Label><Button size="xs" onClick={() => setSources([...sources, { connectionId: sourceConns.find(c => !sources.some(x => x.connectionId === c.id))?.id ?? null, catalog: null, schemas: [] }])}>Add source</Button></div>
                {sources.length === 0 && <p className="muted small" style={{ margin: "0 0 6px" }}>No source yet: the deployment's default source is used. Add one to read from a connection.</p>}
                {sources.map((src, i) => (
                  <SourceRow key={i} index={i} source={src} used={sources.filter((_, j) => j !== i).map(x => x.connectionId)} connections={sourceConns} kindLabel={kindLabel} envKind={KIND_LABEL[config.sourceKind]} envSchemas={available.data ?? []}
                    onChange={patch => editSource(i, patch)} onRemove={() => setSources(sources.filter((_, j) => j !== i))} onPrimary={i > 0 ? () => setSources([src, ...sources.filter((_, j) => j !== i)]) : undefined} />
                ))}
                <div className="muted-2 xs" style={{ marginTop: 4 }}>The primary source is listed first: the catalog browser opens there and short table names resolve against its first schema. Each source has its own schemas; leave them empty to browse all of them.</div>
              </div>
              <div className="grid two" style={{ gap: 12 }}>
                <div><Label>Materialization</Label><select aria-label="Materialization" className="select full" value={mat} onChange={e => setMat(e.target.value as "none" | "view" | "table")}><option value="none">none (graph in Postgres only)</option><option value="view">view (publish triple views)</option><option value="table">table (publish tables, clustered)</option></select></div>
                <div><Label>Target schema</Label><input className="input mono full" value={target} onChange={e => setTarget(e.target.value)} placeholder="finops_metadata.rgm_graph" /></div>
              </div>
              {can("builder") && <div className="row" style={{ justifyContent: "flex-end" }}><Button variant="primary" size="sm" onClick={saveSource} disabled={aiMissing}>Save source settings</Button></div>}
            </div>
            <p className="muted-3" style={{ margin: "12px 0 0", fontSize: 11.5 }}>Credentials live in the connection module and never pass through datagraph.</p>
          </Card>}
          {show("connections") && (CONNECTIONS_URL
            ? <HubConnectionManager canEdit={can("admin")} onChanged={refreshAll} />
            : <Card><div className="row between"><h2 className="h2">Connections</h2><Pill tone="outline">connection module</Pill></div><p className="muted" style={{ marginTop: 8 }}>The connection module is not configured for this front end. Set <span className="mono">VITE_CONNECTIONS_URL</span> to the mf-studio-connectors hub (the gateway route in production, <span className="mono">/hub</span> in development) to add, edit and test connections here.</p></Card>)}
        </div>
        <div className="grid">
          {show("domain") && <Card>
            <h2 className="h2" style={{ marginBottom: 10 }}>Domain</h2>
            <Label>Description</Label><input id="s-desc" className="input full" value={description} onChange={e => setDescription(e.target.value)} style={{ marginBottom: 12 }} />
            <Label>Review quorum</Label><input id="s-quorum" className="input" type="number" min={0} value={quorum} onChange={e => setQuorum(Number(e.target.value) || 0)} style={{ width: 100, marginBottom: 12 }} />
            <Label>Base IRI</Label><input id="s-iri" className="input mono full" value={baseIri} onChange={e => setBaseIri(e.target.value)} />
            {can("builder") && <div className="row" style={{ marginTop: 14, justifyContent: "flex-end" }}><Button variant="primary" size="sm" onClick={saveDomain}>Save changes</Button></div>}
          </Card>}
          {show("mcp") && <Card>
            <h2 className="h2" style={{ marginBottom: 10 }}>MCP policy</h2>
            <div className="row between" style={{ padding: "8px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}><span><strong style={{ fontWeight: 600 }}>Expose this domain to agents</strong><div className="muted small">Active version answers over MCP and GraphQL</div></span><Toggle on={mcp} label="Expose this domain to agents" onChange={async v => { setMcp(v); await api.setMcp(domain.name, v); patch({ ...domain, mcpExposed: v }); say(v ? "Domain exposed to agents" : "Domain hidden from agents"); }} /></div>
            <div className="muted small" style={{ paddingTop: 8, borderTop: "1px solid var(--line-2)" }}>Disabled tools</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>{domain.disabledTools.map(t => <span key={t} className="pill mono" style={{ height: 24, padding: "0 10px", border: "1px solid var(--grey-2)", background: "#fff", fontSize: 12 }}>{t}</span>)}<Button dashed disabled title="Not wired yet: set the policy through the MCP tool set_mcp_policy">+ Disable a tool</Button></div>
          </Card>}
        </div>
      </div>}
    </>
  );
}

/** The catalog a connection is bound to, as the connection module stores it (catalog on Databricks, database elsewhere). */
const connectionCatalog = (c: { config: Record<string, string | number> } | undefined) => (c ? String(c.config.catalog ?? c.config.database ?? "") : "");

/** Schemas of a connection, browsed once through the connection module and cached for the session. */
const browseCache = new Map<string, Promise<string[]>>();
function useHubSchemas(connectionId: string | null): { schemas: string[] | null; loading: boolean; error: string | null } {
  const client = useConnectionsClient();
  const [state, setState] = useState<{ id: string | null; schemas: string[] | null; loading: boolean; error: string | null }>({ id: null, schemas: null, loading: false, error: null });
  useEffect(() => {
    if (!CONNECTIONS_URL || !connectionId) { setState({ id: connectionId, schemas: null, loading: false, error: null }); return; }
    let alive = true;
    setState({ id: connectionId, schemas: null, loading: true, error: null });
    let p = browseCache.get(connectionId);
    if (!p) { p = client.browse(connectionId).then(nodes => nodes.filter(n => n.kind === "schema" || n.kind === "database").map(n => n.name)); browseCache.set(connectionId, p); }
    p.then(schemas => { if (alive) setState({ id: connectionId, schemas, loading: false, error: null }); })
      .catch(e => { browseCache.delete(connectionId); if (alive) setState({ id: connectionId, schemas: null, loading: false, error: e instanceof Error ? e.message : String(e) }); });
    return () => { alive = false; };
  }, [client, connectionId]);
  return state.id === connectionId ? state : { schemas: null, loading: !!connectionId && !!CONNECTIONS_URL, error: null };
}

/** One source of the domain: its connection (which fixes the catalog) and the schemas read from it. */
function SourceRow({ index, source, used, connections, kindLabel, envKind, envSchemas, onChange, onRemove, onPrimary }: {
  index: number; source: DomainSource; used: (string | null)[]; connections: { id: string; name: string; kind: string; config: Record<string, string | number> }[]; kindLabel: (k: string) => string; envKind: string; envSchemas: string[];
  onChange: (patch: Partial<DomainSource>) => void; onRemove: () => void; onPrimary?: () => void;
}) {
  const n = index + 1;
  const conn = connections.find(c => c.id === source.connectionId);
  const hub = useHubSchemas(source.connectionId);
  const [typed, setTyped] = useState("");
  const offered = (hub.schemas ?? (source.connectionId ? [] : envSchemas)).filter(x => !source.schemas.includes(x));
  const addTyped = () => { const x = typed.trim(); if (!x || source.schemas.includes(x)) return; onChange({ schemas: [...source.schemas, x] }); setTyped(""); };
  const pickConnection = (id: string) => { const c = connections.find(x => x.id === id); onChange({ connectionId: id || null, catalog: c ? connectionCatalog(c) || null : source.catalog, schemas: [] }); };
  return (
    <div className="source-row">
      <div className="row" style={{ gap: 8 }}>
        <span className="pill" style={{ flex: "none" }}>{index === 0 ? "primary" : `source ${n}`}</span>
        <select aria-label={`Source connection ${n}`} className="select sm" style={{ flex: 2, minWidth: 0 }} value={source.connectionId ?? ""} onChange={e => pickConnection(e.target.value)}>
          <option value="">Deployment default ({envKind})</option>
          {connections.map(c => <option key={c.id} value={c.id} disabled={used.includes(c.id)}>{c.name} · {kindLabel(c.kind)}</option>)}
        </select>
        {conn
          ? <span className="row" style={{ flex: 1, minWidth: 0, gap: 6, fontSize: 12.5 }} title="The catalog is part of the connection; change it in the connection module"><span className="muted-2 xs">catalog</span><span className="mono" style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{connectionCatalog(conn) || "default"}</span></span>
          : <input aria-label={`Catalog of source ${n}`} className="input mono sm" style={{ flex: 1, minWidth: 0 }} placeholder="catalog" value={source.catalog ?? ""} onChange={e => onChange({ catalog: e.target.value || null })} />}
        {onPrimary && <button type="button" className="chip-act" aria-label={`Make source ${n} primary`} title="Make primary" onClick={onPrimary}><Icon name="check" size={10} /></button>}
        <button type="button" className="chip-act" aria-label={`Remove source ${n}`} title="Remove source" onClick={onRemove}>×</button>
      </div>
      <div style={{ marginTop: 8 }}><SchemaList schemas={source.schemas} onChange={schemas => onChange({ schemas })} /></div>
      <div className="row" style={{ gap: 6, marginTop: 6 }}>
        {hub.loading && <span className="row muted small"><Spinner blue />Loading schemas from the connection module…</span>}
        {hub.schemas && <select aria-label={`Schema for source ${n}`} className="select sm" style={{ flex: 1, minWidth: 0 }} value="" onChange={e => { if (e.target.value) onChange({ schemas: [...source.schemas, e.target.value] }); }}>
          <option value="">Add a schema…</option>
          {offered.map(x => <option key={x} value={x}>{x}</option>)}
        </select>}
        {!hub.loading && !hub.schemas && <>
          <input className="input mono sm" list={`schema-options-${index}`} aria-label={`Schema name for source ${n}`} placeholder="schema name" value={typed} onChange={e => setTyped(e.target.value)} onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addTyped(); } }} style={{ flex: 1, minWidth: 0 }} />
          <datalist id={`schema-options-${index}`}>{offered.map(x => <option key={x} value={x} />)}</datalist>
          <Button size="sm" aria-label={`Add schema to source ${n}`} onClick={addTyped} disabled={!typed.trim() || source.schemas.includes(typed.trim())}>Add</Button>
        </>}
      </div>
      {hub.error && <div className="xs" style={{ marginTop: 4, color: "var(--orange-text)" }}>Could not browse this connection: {hub.error}. Type the schema names instead.</div>}
    </div>
  );
}

/** Ordered schema chips: the first is the default; any other can be promoted or removed. */
function SchemaList({ schemas, onChange }: { schemas: string[]; onChange: (s: string[]) => void }) {
  if (schemas.length === 0) return <ul aria-label="Schemas" className="schema-list"><li className="muted small" style={{ listStyle: "none" }}>No schema chosen · every schema of this source is browsed. Add some to narrow it down.</li></ul>;
  return (
    <ul aria-label="Schemas" className="schema-list">
      {schemas.map((s, i) => (
        <li key={s} className="schema-chip">
          <span className="mono">{s}</span>
          {i === 0 ? <span className="pill blue" style={{ height: 18, fontSize: 10.5 }}>default</span>
            : <button type="button" className="chip-act" aria-label={`Make ${s} the default`} title="Make default" onClick={() => onChange([s, ...schemas.filter(x => x !== s)])}><Icon name="check" size={10} /></button>}
          <button type="button" className="chip-act" aria-label={`Remove ${s}`} title="Remove" onClick={() => onChange(schemas.filter(x => x !== s))}>×</button>
        </li>
      ))}
    </ul>
  );
}

function TestNotice({ r }: { r: ConnResult }) {
  return (
    <div className="notice" style={{ borderColor: r.ok ? "var(--blue-border)" : "var(--orange)", background: r.ok ? "var(--blue-soft)" : "#fff" }}>
      <div className="row" style={{ fontWeight: 700, color: r.ok ? "var(--blue)" : "var(--orange)" }}><Dot color={r.ok ? "var(--blue)" : "var(--orange)"} size={8} />{r.title}{r.latency_ms != null && <span className="muted-2 xs" style={{ fontWeight: 500 }}>· {r.latency_ms} ms</span>}</div>
      <div className="mono" style={{ marginTop: 4, color: "var(--ink-2)", fontSize: 11.5, whiteSpace: "pre-wrap" }}>{r.detail}</div>
      {r.action && <div style={{ marginTop: 6 }}>{r.action}</div>}
    </div>
  );
}

/** The connection module's own list, form and test report, rendered with @polestar/connections. */
function HubConnectionManager({ canEdit, onChanged }: { canEdit: boolean; onChanged: () => void }) {
  const { api, say } = useApp();
  const client = useConnectionsClient();
  const types = useConnectionTypes();
  const list = useConnections();
  const rowTest = useTestConnection();
  const [testingId, setTestingId] = useState<string | null>(null);
  const [dialog, setDialog] = useState<{ open: boolean; edit?: Connection }>({ open: false });
  const typeLabel = (t: string) => types.data?.find(x => x.type === t)?.display_name ?? KIND_LABEL[t] ?? t;
  const changed = () => { list.reload(); onChanged(); };

  return (
    <>
      <Card flush>
        <div className="card-head" style={{ alignItems: "center" }}><h2 className="h2">Connections <Pill tone="blue" style={{ marginLeft: 6 }}>connection module</Pill></h2>{canEdit && <Button size="sm" variant="primary" onClick={() => setDialog({ open: true })}>New connection</Button>}</div>
        <div className="grid-head" style={{ gridTemplateColumns: "1.2fr 1fr 1.6fr 1fr auto" }}><span>Name</span><span>Kind</span><span>Host</span><span>Last test</span><span /></div>
        {list.loading && <div style={{ padding: 20 }}><Skeleton h={16} /></div>}
        {list.error && <div style={{ padding: "0 20px 16px" }}><ErrorNotice error={`The connection module did not answer: ${list.error.message}`} action={<span className="small">Is the hub running at the configured URL?</span>} /></div>}
        {(list.data ?? []).map(c => (
          <div key={c.id}>
            <div className="grid-row" style={{ gridTemplateColumns: "1.2fr 1fr 1.6fr 1fr auto", padding: "10px 20px" }}>
              <span style={{ fontWeight: 600 }}>{c.name}</span>
              <Pill tone={isAiKind(c.type, types.data) ? "outline" : "blue"}>{typeLabel(c.type)}</Pill>
              <span className="mono small" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{String(c.config.host ?? c.config.endpoint ?? "—")}</span>
              <span className="row small"><Dot color={c.last_test_ok == null ? "var(--grey)" : c.last_test_ok ? "var(--blue)" : "var(--orange)"} />{c.last_test_ok == null ? "never" : c.last_test_ok ? "ok" : "failed"}{c.last_tested_at && <span className="muted-3 xs">· {new Date(c.last_tested_at).toLocaleString()}</span>}</span>
              <span className="row" style={{ gap: 4 }}>
                <Button size="xs" disabled={rowTest.testing} onClick={async () => { setTestingId(c.id); const r = await rowTest.run({ id: c.id }); if (r) say(`${c.name}: ${r.ok ? "connected" : "failed"}`); changed(); }}>Test</Button>
                {canEdit && <Button size="xs" onClick={() => setDialog({ open: true, edit: c })}>Edit</Button>}
                {canEdit && <Button size="xs" variant="danger" onClick={async () => { await client.deleteConnection(c.id); await api.detachConnection(c.id).catch(() => {}); say(`Connection ${c.name} deleted`); changed(); }}>Delete</Button>}
              </span>
            </div>
            {testingId === c.id && (rowTest.testing || rowTest.report) && <div style={{ padding: "0 20px 14px" }}><TestReportView report={rowTest.report} testing={rowTest.testing} /></div>}
          </div>
        ))}
        {list.data?.length === 0 && <p className="muted" style={{ padding: 20 }}>No connections yet. Add the warehouse this domain reads from, and an AI provider for drafts.</p>}
      </Card>
      <ConnectionDialog open={dialog.open} edit={dialog.edit} types={types.data ?? []} onClose={() => setDialog({ open: false })} onSaved={c => { setDialog({ open: false }); say(`Connection ${c.name} saved`); changed(); }} />
    </>
  );
}

/** Create or edit a connection through the module: its JSON Schema renders the form, its hub runs the test. */
function ConnectionDialog({ open, edit, types, onClose, onSaved }: { open: boolean; edit?: Connection; types: ConnectorSummary[]; onClose: () => void; onSaved: (c: Connection) => void }) {
  const client = useConnectionsClient();
  const { run, report, testing, reset } = useTestConnection();
  const [type, setType] = useState("");
  const [name, setName] = useState("");
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const sorted = useMemo(() => [...types].sort((a, b) => a.category.localeCompare(b.category) || a.display_name.localeCompare(b.display_name)), [types]);
  useEffect(() => {
    if (!open) return;
    reset(); setErrors({}); setError(null);
    if (edit) { setType(edit.type); setName(edit.name); setConfig(edit.config); }
    else { setType(types.find(t => t.type === "databricks")?.type ?? types[0]?.type ?? ""); setName(""); setConfig({}); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, edit, types]);
  const cleaned = () => Object.fromEntries(Object.entries(config).filter(([, v]) => v !== "" && v !== undefined && v !== "********"));
  const save = async () => {
    setSaving(true); setError(null); setErrors({});
    try { onSaved(edit ? await client.updateConnection(edit.id, { name, config: cleaned() }) : await client.createConnection({ name, type, config: cleaned() })); }
    catch (e) {
      if (e instanceof ValidationError) setErrors(Object.fromEntries(e.errors.map(line => { const [field, ...rest] = line.split(": "); return [field, rest.join(": ")]; })));
      else setError(e instanceof Error ? e.message : String(e));
    } finally { setSaving(false); }
  };
  return (
    <Dialog title={edit ? `Edit ${edit.name}` : "New connection"} open={open} onClose={onClose} width={560}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="outline" disabled={testing || !type} onClick={() => run({ type, config: cleaned() })}>{testing && <Spinner blue />}Test</Button><Button variant="primary" disabled={saving || !name.trim() || !type} onClick={save}>{saving && <Spinner />}{edit ? "Save changes" : "Create connection"}</Button></>}>
      <div className="grid two" style={{ gap: 12, marginBottom: 12 }}>
        <div><Label>Name</Label><input id="cn-name" className="input full" placeholder="warehouse" value={name} onChange={e => setName(e.target.value)} /></div>
        <div><Label>Kind</Label><select id="cn-kind" aria-label="Kind" className="select full" value={type} disabled={!!edit} onChange={e => { setType(e.target.value); setConfig({}); reset(); }}>{sorted.map(t => <option key={t.type} value={t.type}>{t.display_name}{t.category === "ai" ? " (AI)" : ""}</option>)}</select></div>
      </div>
      {type && <ConnectionForm key={`${type}-${edit?.id ?? "new"}`} type={type} value={edit?.config} errors={errors} onChange={setConfig} />}
      <div style={{ marginTop: 12 }}><TestReportView report={report} testing={testing} /></div>
      {error && <ErrorNotice error={error} />}
    </Dialog>
  );
}
