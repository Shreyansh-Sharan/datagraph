import { useEffect, useMemo, useState } from "react";
import { Button, Card, Dialog, Dot, ErrorNotice, KV, Label, Pill, Skeleton, Spinner, Toggle } from "@/components/ui";
import { useApp, useLoad } from "@/state/app";
import { useDomain } from "@/state/domain";
import type { ConnResult, ConnectionRec, ConnectorSpec, ConnectorKind } from "@/api";

const KIND_LABEL: Record<string, string> = { postgres: "Postgres", databricks: "Databricks", sqlserver: "SQL Server", azure_openai: "Azure OpenAI" };

export function Settings() {
  const { api, config, say, can } = useApp();
  const { domain, patch } = useDomain();
  const facts = useLoad(() => api.sourceFacts(domain.name), [domain.name]);
  const conns = useLoad(() => api.connections(), []);
  const specs = useLoad(() => api.connectors(), []);
  const [testing, setTesting] = useState(false);
  const [conn, setConn] = useState<ConnResult | null>(null);
  const [mcp, setMcp] = useState(domain.mcpExposed);
  const [dialog, setDialog] = useState<{ open: boolean; edit?: ConnectionRec }>({ open: false });
  // domain form
  const [description, setDescription] = useState(domain.description);
  const [quorum, setQuorum] = useState(domain.quorum);
  const [baseIri, setBaseIri] = useState(domain.base_iri);
  const [connectionId, setConnectionId] = useState(domain.connectionId ?? "");
  const [aiId, setAiId] = useState(domain.aiConnectionId ?? "");
  const [defCatalog, setDefCatalog] = useState("");
  const [defSchema, setDefSchema] = useState("");
  const [mat, setMat] = useState<"none" | "view" | "table">("none");
  const [target, setTarget] = useState("");
  useEffect(() => { setDescription(domain.description); setQuorum(domain.quorum); setBaseIri(domain.base_iri); setConnectionId(domain.connectionId ?? ""); setAiId(domain.aiConnectionId ?? ""); }, [domain]);
  useEffect(() => { if (facts.data) { setDefCatalog(facts.data.catalog ?? ""); setDefSchema(facts.data.schema ?? ""); setMat((facts.data.materialization as "none" | "view" | "table") || "none"); setTarget(facts.data.target_schema ?? ""); } }, [facts.data]);

  const sources = (conns.data ?? []).filter(c => c.kind !== "azure_openai");
  const ais = (conns.data ?? []).filter(c => c.kind === "azure_openai");
  const f = facts.data;
  const sourceRows: [string, string][] = f ? [["Kind", f.kind], ["Connection", f.connection ?? "deployment default (env)"], ...(f.host ? [["Host", f.host] as [string, string]] : []), ["Catalog · schema", `${f.catalog ?? "—"} · ${f.schema ?? "—"}`], ["Auth mode", `${f.auth_mode} · ${f.auth_header}`], ["Materialization", f.materialization + (f.target_schema ? ` → ${f.target_schema}` : "")], ["AI", f.ai ? `${f.ai.connection ?? f.ai.kind} · ${f.ai.deployment ?? "—"}` : "none"]] : [];

  const test = async () => {
    if (testing) return; setTesting(true); setConn(null);
    try { setConn(f?.connection_id ? await api.testConnectionById(f.connection_id) : await api.testConnection()); conns.reload(); } catch (e) { setConn({ ok: false, title: "Connection failed", detail: e instanceof Error ? e.message : String(e) }); } finally { setTesting(false); }
  };
  const saveSource = async () => {
    try {
      patch(await api.updateDomain(domain.name, { connection_id: connectionId || null, ai_connection_id: aiId || null, default_catalog: defCatalog || null, default_schema: defSchema || null, materialization: mat, target_schema: target || null }));
      facts.reload(); say("Source settings saved");
    } catch (e) { say(e instanceof Error ? e.message : String(e)); }
  };
  const saveDomain = async () => {
    try { patch(await api.updateDomain(domain.name, { description, review_quorum: quorum, base_iri: baseIri })); say("Domain settings saved"); }
    catch (e) { say(e instanceof Error ? e.message : String(e)); }
  };

  return (
    <>
      <div className="page-head"><div><h1>Settings</h1><p>Domain description, what MCP exposes, the source warehouse and AI provider this domain uses, and the connections behind them.</p></div></div>
      <div className="grid two">
        <div className="grid">
          <Card>
            <div className="row between" style={{ marginBottom: 10 }}><h2 className="h2">Source</h2><Button size="sm" variant="outline" style={{ height: 30 }} onClick={test}>{testing && <Spinner blue />}Test connection</Button></div>
            {facts.loading && <Skeleton h={120} />}
            {facts.error && <ErrorNotice error={facts.error} />}
            {sourceRows.map(([k, v]) => <KV key={k} k={k} v={v} />)}
            {conn && <TestNotice r={conn} />}
            <div style={{ marginTop: 16, display: "grid", gap: 12 }}>
              <div className="grid two" style={{ gap: 12 }}>
                <div><Label>Source connection</Label><select id="src-conn" aria-label="Source connection" className="select full" value={connectionId} onChange={e => setConnectionId(e.target.value)}><option value="">Deployment default ({KIND_LABEL[config.sourceKind]})</option>{sources.map(c => <option key={c.id} value={c.id}>{c.name} · {KIND_LABEL[c.kind] ?? c.kind}</option>)}</select></div>
                <div><Label>AI connection</Label><select id="ai-conn" aria-label="AI connection" className="select full" value={aiId} onChange={e => setAiId(e.target.value)}><option value="">None</option>{ais.map(c => <option key={c.id} value={c.id}>{c.name} · {String(c.config.deployment ?? "")}</option>)}</select></div>
              </div>
              <div className="grid two" style={{ gap: 12 }}>
                <div><Label>Default catalog</Label><input className="input mono full" value={defCatalog} onChange={e => setDefCatalog(e.target.value)} placeholder="rgm" /></div>
                <div><Label>Default schema</Label><input className="input mono full" value={defSchema} onChange={e => setDefSchema(e.target.value)} placeholder="gold" /></div>
              </div>
              <div className="grid two" style={{ gap: 12 }}>
                <div><Label>Materialization</Label><select aria-label="Materialization" className="select full" value={mat} onChange={e => setMat(e.target.value as "none" | "view" | "table")}><option value="none">none (graph in Postgres only)</option><option value="view">view (publish triple views)</option><option value="table">table (publish tables, clustered)</option></select></div>
                <div><Label>Target schema</Label><input className="input mono full" value={target} onChange={e => setTarget(e.target.value)} placeholder="finops_metadata.rgm_graph" /></div>
              </div>
              {can("builder") && <div className="row" style={{ justifyContent: "flex-end" }}><Button variant="primary" size="sm" onClick={saveSource}>Save source settings</Button></div>}
            </div>
            <p className="muted-3" style={{ margin: "12px 0 0", fontSize: 11.5 }}>Secrets are encrypted at rest and never returned by the API.</p>
          </Card>
          <Card flush>
            <div className="card-head" style={{ alignItems: "center" }}><h2 className="h2">Connections</h2>{can("admin") && <Button size="sm" variant="primary" onClick={() => setDialog({ open: true })}>New connection</Button>}</div>
            <div className="grid-head" style={{ gridTemplateColumns: "1.2fr 1fr 1.6fr 1fr auto" }}><span>Name</span><span>Kind</span><span>Host</span><span>Last test</span><span /></div>
            {conns.loading && <div style={{ padding: 20 }}><Skeleton h={16} /></div>}
            {(conns.data ?? []).map(c => (
              <div key={c.id} className="grid-row" style={{ gridTemplateColumns: "1.2fr 1fr 1.6fr 1fr auto", padding: "10px 20px" }}>
                <span style={{ fontWeight: 600 }}>{c.name}</span>
                <Pill tone={c.kind === "azure_openai" ? "outline" : "blue"}>{KIND_LABEL[c.kind] ?? c.kind}</Pill>
                <span className="mono small" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{String(c.config.host ?? c.config.endpoint ?? "—")}</span>
                <span className="row small"><Dot color={c.last_test ? (c.last_test.ok ? "var(--blue)" : "var(--orange)") : "var(--grey)"} />{c.last_test ? (c.last_test.ok ? `ok · ${c.last_test.latency_ms ?? 0} ms` : "failed") : "never"}</span>
                <span className="row" style={{ gap: 4 }}>
                  <Button size="xs" onClick={async () => { try { const r = await api.testConnectionById(c.id); say(`${c.name}: ${r.title} · ${r.detail}`); conns.reload(); } catch (e) { say(e instanceof Error ? e.message : String(e)); } }}>Test</Button>
                  {can("admin") && <Button size="xs" onClick={() => setDialog({ open: true, edit: c })}>Edit</Button>}
                  {can("admin") && <Button size="xs" variant="danger" onClick={async () => { await api.deleteConnection(c.id); conns.reload(); facts.reload(); say(`Connection ${c.name} deleted`); }}>Delete</Button>}
                </span>
              </div>
            ))}
            {conns.data?.length === 0 && <p className="muted" style={{ padding: 20 }}>No connections yet. The deployment's environment source is used until one is attached.</p>}
          </Card>
        </div>
        <div className="grid">
          <Card>
            <h2 className="h2" style={{ marginBottom: 10 }}>MCP policy</h2>
            <div className="row between" style={{ padding: "8px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}><span><strong style={{ fontWeight: 600 }}>Expose this domain to agents</strong><div className="muted small">Active version answers over MCP and GraphQL</div></span><Toggle on={mcp} label="Expose this domain to agents" onChange={async v => { setMcp(v); await api.setMcp(domain.name, v); patch({ ...domain, mcpExposed: v }); say(v ? "Domain exposed to agents" : "Domain hidden from agents"); }} /></div>
            <div className="muted small" style={{ paddingTop: 8, borderTop: "1px solid var(--line-2)" }}>Disabled tools</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>{domain.disabledTools.map(t => <span key={t} className="pill mono" style={{ height: 24, padding: "0 10px", border: "1px solid var(--grey-2)", background: "#fff", fontSize: 12 }}>{t}</span>)}<Button dashed onClick={() => say("Pick a tool to disable")}>+ Disable a tool</Button></div>
          </Card>
          <Card>
            <h2 className="h2" style={{ marginBottom: 10 }}>Domain</h2>
            <Label>Description</Label><input id="s-desc" className="input full" value={description} onChange={e => setDescription(e.target.value)} style={{ marginBottom: 12 }} />
            <Label>Review quorum</Label><input id="s-quorum" className="input" type="number" min={0} value={quorum} onChange={e => setQuorum(Number(e.target.value) || 0)} style={{ width: 100, marginBottom: 12 }} />
            <Label>Base IRI</Label><input id="s-iri" className="input mono full" value={baseIri} onChange={e => setBaseIri(e.target.value)} />
            {can("builder") && <div className="row" style={{ marginTop: 14, justifyContent: "flex-end" }}><Button variant="primary" size="sm" onClick={saveDomain}>Save changes</Button></div>}
          </Card>
        </div>
      </div>
      <ConnectionDialog open={dialog.open} edit={dialog.edit} specs={specs.data ?? []} onClose={() => setDialog({ open: false })} onSaved={c => { setDialog({ open: false }); conns.reload(); facts.reload(); say(`Connection ${c.name} saved`); }} />
    </>
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

/** Create or edit a connection: the kind picks the field list from the connector spec; Test probes before Save. */
export function ConnectionDialog({ open, edit, specs, onClose, onSaved }: { open: boolean; edit?: ConnectionRec; specs: ConnectorSpec[]; onClose: () => void; onSaved: (c: ConnectionRec) => void }) {
  const { api } = useApp();
  const [kind, setKind] = useState<ConnectorKind>("databricks");
  const [name, setName] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [result, setResult] = useState<ConnResult | null>(null);
  const [busy, setBusy] = useState<"test" | "save" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const spec = useMemo(() => specs.find(s => s.kind === kind), [specs, kind]);
  useEffect(() => {
    if (!open) return;
    setResult(null); setError(null);
    if (edit) { setKind(edit.kind); setName(edit.name); setValues(Object.fromEntries(Object.entries(edit.config).map(([k, v]) => [k, String(v)]))); }
    else { setKind("databricks"); setName(""); setValues({}); }
  }, [open, edit]);
  useEffect(() => { if (spec && !edit) setValues(v => ({ ...Object.fromEntries(spec.fields.filter(f => f.default != null).map(f => [f.name, String(f.default)])), ...v })); }, [spec, edit]);
  if (!spec && specs.length === 0) return null;
  const config = () => { const cfg: Record<string, string | number> = {}; for (const f of spec?.fields ?? []) { const v = values[f.name]; if (v === undefined || v === "" || f.name === spec?.secret_field) continue; cfg[f.name] = f.kind === "number" ? Number(v) : v; } return cfg; };
  const secret = () => (spec ? values[spec.secret_field] || undefined : undefined);
  const run = async (mode: "test" | "save") => {
    if (!spec) return; setBusy(mode); setError(null);
    try {
      if (mode === "test") setResult(await api.testConnectionDraft({ kind, config: config(), secret: secret() }));
      else onSaved(edit ? await api.updateConnection(edit.id, { name, config: config(), secret: secret() }) : await api.createConnection({ name, kind, config: config(), secret: secret() }));
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(null); }
  };
  return (
    <Dialog title={edit ? `Edit ${edit.name}` : "New connection"} open={open} onClose={onClose} width={520}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="outline" onClick={() => run("test")} disabled={busy !== null}>{busy === "test" && <Spinner blue />}Test</Button><Button variant="primary" onClick={() => run("save")} disabled={busy !== null || !name.trim()}>{busy === "save" && <Spinner />}{edit ? "Save changes" : "Create connection"}</Button></>}>
      <div className="grid two" style={{ gap: 12, marginBottom: 12 }}>
        <div><Label>Name</Label><input id="cn-name" className="input full" placeholder="warehouse" value={name} onChange={e => setName(e.target.value)} /></div>
        <div><Label>Kind</Label><select id="cn-kind" aria-label="Kind" className="select full" value={kind} disabled={!!edit} onChange={e => { setKind(e.target.value as ConnectorKind); setValues({}); setResult(null); }}>{specs.map(s => <option key={s.kind} value={s.kind}>{s.label}{s.category === "ai" ? " (AI)" : ""}</option>)}</select></div>
      </div>
      <div style={{ display: "grid", gap: 10 }}>
        {(spec?.fields ?? []).map(f => (
          <div key={f.name}>
            <Label>{f.label}{f.required && <span style={{ color: "var(--orange)" }}> *</span>}</Label>
            {f.kind === "select"
              ? <select aria-label={f.label} className="select full" value={values[f.name] ?? String(f.default ?? "")} onChange={e => setValues(v => ({ ...v, [f.name]: e.target.value }))}>{f.options.map(o => <option key={o} value={o}>{o}</option>)}</select>
              : <input aria-label={f.label} className={`input full ${f.kind === "password" ? "" : "mono"}`} type={f.kind === "password" ? "password" : f.kind === "number" ? "number" : "text"} value={values[f.name] ?? ""} placeholder={f.name === spec?.secret_field && edit?.has_secret ? "•••••• (unchanged)" : f.help ?? ""} onChange={e => setValues(v => ({ ...v, [f.name]: e.target.value }))} />}
            {f.help && f.kind !== "password" && <div className="muted-2 xs" style={{ marginTop: 3 }}>{f.help}</div>}
          </div>
        ))}
      </div>
      {result && <TestNotice r={result} />}
      {error && <ErrorNotice error={error} />}
    </Dialog>
  );
}
