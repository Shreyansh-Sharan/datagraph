// Home: the domains, as cards or as a list, with a filter. The assistant lives in the Spotlight
// (Cmd+K) and on the Ask screen, not here.
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "@/components/icons";
import { Button, Card, Dialog, Dot, ErrorNotice, Label, Skeleton } from "@/components/ui";
import { useApp, useLoad } from "@/state/app";
import type { DomainSummary } from "@/api";

type View = "cards" | "list";
const VIEW_KEY = "dg.home.view";
const readView = (): View => { try { return localStorage.getItem(VIEW_KEY) === "list" ? "list" : "cards"; } catch { return "cards"; } };

export function Home() {
  const { api, config, say } = useApp();
  const navigate = useNavigate();
  const { data, error, loading, reload } = useLoad(() => api.domains(), []);
  const [dialog, setDialog] = useState(false);
  const [view, setView] = useState<View>(readView);
  const [q, setQ] = useState("");
  useEffect(() => { try { localStorage.setItem(VIEW_KEY, view); } catch { /* per-viewer convenience only */ } }, [view]);
  const dbx = config.sourceKind === "databricks";
  const open = (d: DomainSummary, screen = "") => navigate(`/d/${encodeURIComponent(d.name)}${screen ? `/${screen}` : ""}`);
  const rows = useMemo(() => {
    const t = q.trim().toLowerCase();
    return (data ?? []).filter(d => !t || d.name.toLowerCase().includes(t) || (d.description ?? "").toLowerCase().includes(t) || d.catalog.toLowerCase().includes(t)).map(d => summarise(d, dbx));
  }, [data, q, dbx]);

  return (
    <div className="home">
      <div className="home-head">
        <div><h1>Domains</h1><p className="muted">One knowledge graph each, with its own source, versions, review quorum and MCP policy. Open one to work in it.</p></div>
        <div className="row" style={{ flex: "none", gap: 8 }}><Button onClick={() => say("Choose a bundle file to import")}>Import bundle</Button><Button variant="primary" onClick={() => setDialog(true)}>New domain</Button></div>
      </div>
      <div className="home-tools">
        <label className="home-filter"><Icon name="search" size={14} /><input aria-label="Filter domains" placeholder="Filter domains" value={q} onChange={e => setQ(e.target.value)} /></label>
        <div className="seg" role="radiogroup" aria-label="View">
          <button type="button" role="radio" aria-checked={view === "cards"} aria-label="Card view" className={view === "cards" ? "on" : ""} onClick={() => setView("cards")}><Icon name="overview" size={14} />Cards</button>
          <button type="button" role="radio" aria-checked={view === "list"} aria-label="List view" className={view === "list" ? "on" : ""} onClick={() => setView("list")}><Icon name="triples" size={14} />List</button>
        </div>
      </div>
      {error && <ErrorNotice error={error} action={<Button size="sm" onClick={reload}>Retry</Button>} />}
      {loading && !data && (view === "list" ? <Skeleton h={160} /> : <div className="home-cards">{[0, 1, 2].map(i => <Card key={i}><Skeleton h={34} w={160} /><Skeleton h={16} style={{ marginTop: 14 }} /><Skeleton h={16} /><Skeleton h={16} /></Card>)}</div>)}
      {data && rows.length === 0 && <p className="muted home-empty">{q ? `No domain matches “${q}”.` : "No domain yet. Create one to start."}</p>}
      {rows.length > 0 && (view === "list" ? (
        <table className="dom-table" aria-label="Domains">
          <thead><tr><th>Domain</th><th>Status</th><th className="num">Triples</th><th>Last build</th><th>Source</th><th aria-label="Actions" /></tr></thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.d.name} onClick={() => open(r.d)} className="link">
                <td><div className="dom-name"><span className="dom-avatar">{r.d.name[0].toUpperCase()}</span><div><a href="#" onClick={e => { e.preventDefault(); open(r.d); }}>{r.d.name}</a><div className="muted sub">{r.d.description || "No description"}</div></div></div></td>
                <td><span className="pill"><Dot color={r.dot} />{r.state}</span></td>
                <td className="num">{r.d.triples}</td>
                <td><div className={`build ${r.buildTone}`}>{r.buildStatus}</div><div className="muted xs">{r.buildWhen || "—"}</div></td>
                <td className="mono small src" title={r.source}>{r.source}</td>
                <td className="acts" onClick={e => e.stopPropagation()}>
                  <Button size="sm" onClick={() => open(r.d, "ask")} aria-label={`Ask ${r.d.name}`}><Icon name="ask" size={13} />Ask</Button>
                  <Button size="sm" onClick={() => open(r.d, "settings")} aria-label={`Configure ${r.d.name}`} title="Configure"><Icon name="settings" size={13} /></Button>
                </td>
              </tr>))}
          </tbody>
        </table>
      ) : (
        <div className="home-cards">
          {rows.map(r => {
            const d = r.d;
            const cfg = [["Source", r.source], ["Base IRI", d.base_iri], ["Review quorum", String(d.quorum)], ["MCP", d.mcpExposed ? `exposed · ${d.disabledTools.length} tools off` : "hidden"]];
            return (
              <Card key={d.name} style={{ borderRadius: 12, display: "flex", flexDirection: "column", gap: 12 }}>
                <div className="row between" style={{ gap: 10 }}>
                  <a href="#" onClick={e => { e.preventDefault(); open(d); }} className="dom-name" style={{ color: "var(--ink)" }}>
                    <span className="dom-avatar">{d.name[0].toUpperCase()}</span>
                    <span style={{ minWidth: 0 }}><span style={{ display: "block", fontSize: 16, fontWeight: 800, color: "var(--blue)" }}>{d.name}</span><span className="muted sub" style={{ display: "block", fontSize: 12 }}>{d.description || "No description"}</span></span>
                  </a>
                  <span className="pill lg" style={{ flex: "none" }}><Dot color={r.dot} />{r.state}</span>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 8 }}>
                  {[["Triples", d.triples], ["Versions", String(d.versions.length)], ["Last build", d.lastBuild]].map(([k, v]) => <div key={k}><div className="label-caps" style={{ fontSize: 10.5, color: "var(--muted-3)" }}>{k}</div><div style={{ fontSize: 16, fontWeight: 800, letterSpacing: "-.02em", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{v}</div></div>)}
                </div>
                <div style={{ borderTop: "1px solid var(--line-2)", paddingTop: 10, display: "grid", gap: 5 }}>
                  {cfg.map(([k, v]) => <div key={k} className="row between" style={{ fontSize: 12, gap: 10 }}><span className="muted-2">{k}</span><span className="mono" style={{ fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{v}</span></div>)}
                </div>
                <div className="row" style={{ gap: 6, marginTop: "auto" }}>
                  <Button variant="primary" size="sm" style={{ flex: 1, height: 30 }} onClick={() => open(d)}>Open</Button>
                  <Button size="sm" style={{ height: 30 }} onClick={() => open(d, "ask")}>Ask</Button>
                  <Button size="sm" style={{ height: 30 }} onClick={() => open(d, "settings")}>Configure</Button>
                </div>
              </Card>
            );
          })}
        </div>
      ))}
      <NewDomainDialog open={dialog} onClose={() => setDialog(false)} onCreated={d => { setDialog(false); say(`Domain ${d.name} created`); open(d); }} />
    </div>
  );
}

/** What both views show about a domain: its state, build and source, spelled once. */
function summarise(d: DomainSummary, dbx: boolean) {
  const act = d.versions.find(v => v.active); const dr = d.versions.find(v => v.status === "draft");
  const more = d.sources.length > 1 ? ` +${d.sources.length - 1} source${d.sources.length > 2 ? "s" : ""}` : d.schemas.length > 1 ? ` +${d.schemas.length - 1}` : "";
  const [first, ...rest] = d.lastBuild.split(" · ");
  const known = ["succeeded", "failed", "running", "cancelled", "never"].includes(first);
  const buildStatus = known ? first : "built", buildWhen = known ? rest.join(" · ") : d.lastBuild;
  return {
    d,
    state: act ? `v${act.version} active` : dr ? `v${dr.version} draft` : "no version",
    dot: act ? "var(--blue)" : dr ? "var(--grey)" : "var(--grey-2)",
    source: dbx ? `databricks · ${d.catalog}.${d.schema}${more}` : `postgres · ${d.catalog}_${d.schema}${more}`,
    buildStatus, buildWhen,
    buildTone: buildStatus === "succeeded" ? "ok" : buildStatus === "failed" ? "bad" : buildStatus === "running" ? "run" : "none",
  };
}

export function NewDomainDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (d: DomainSummary) => void }) {
  const { api } = useApp();
  const [name, setName] = useState(""); const [description, setDescription] = useState(""); const [baseIri, setBaseIri] = useState("http://polestar.ai/"); const [quorum, setQuorum] = useState(1);
  const [aiId, setAiId] = useState(""); const [sourceId, setSourceId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const conns = useLoad(() => open ? api.connections().catch(() => []) : Promise.resolve([]), [open]);
  const isAi = (kind: string) => kind.includes("openai") || kind.includes("llm");
  const ais = (conns.data ?? []).filter(c => isAi(c.kind)); const sourceConns = (conns.data ?? []).filter(c => !isAi(c.kind));
  const valid = /^[A-Za-z0-9_-]+$/.test(name);
  const slug = name.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "");
  const aiMissing = ais.length > 0 && !aiId;
  const create = async () => {
    try {
      onCreated(await api.createDomain({ name, description, base_iri: baseIri.endsWith("/") ? `${baseIri}${name}/` : baseIri, quorum, ai_connection_id: aiId || null, sources: sourceId ? [{ connection_id: sourceId, catalog: null, schemas: [] }] : [] }));
      setName(""); setDescription(""); setAiId(""); setSourceId(""); setError(null);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <Dialog title="New domain" open={open} onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!valid || aiMissing} onClick={create}>Create domain</Button></>}>
      <Label>Name</Label>
      <input id="nd-name" className="input mono full" placeholder="hr" aria-label="Name" value={name} onChange={e => setName(e.target.value)} aria-invalid={!!name && !valid} />
      {name && !valid
        ? <div className="xs" style={{ margin: "4px 0 12px", color: "var(--orange-text)", fontWeight: 600 }}>{/\s/.test(name) ? "Spaces are not allowed" : "Only letters, digits, - and _ are allowed"}{slug && slug !== name ? <>, try <a href="#" className="mono" onClick={e => { e.preventDefault(); setName(slug); }}>{slug}</a></> : ""}.</div>
        : <div className="muted-2 xs" style={{ margin: "4px 0 12px" }}>Letters, digits, - and _ only. The name is also the domain's URL and catalog.</div>}
      <Label>Description</Label>
      <input id="nd-desc" className="input full" placeholder="People and departments" value={description} onChange={e => setDescription(e.target.value)} style={{ marginBottom: 12 }} />
      <Label>Base IRI</Label>
      <input id="nd-iri" className="input mono full" value={baseIri} onChange={e => setBaseIri(e.target.value)} style={{ marginBottom: 12 }} />
      <div className="grid two" style={{ gap: 12, marginBottom: 12 }}>
        <div><Label>AI connection</Label><select id="nd-ai" aria-label="AI connection" className="select full" value={aiId} onChange={e => setAiId(e.target.value)} aria-invalid={aiMissing}><option value="">{ais.length ? "Choose one…" : "None available"}</option>{ais.map(c => <option key={c.id} value={c.id}>{c.name} · {String(c.config.deployment ?? "")}</option>)}</select>{ais.length > 0 && <div className="muted-2 xs" style={{ marginTop: 4 }}>Required: drafts the ontology and answers Ask.</div>}</div>
        <div><Label>Source connection</Label><select id="nd-src" aria-label="Source connection" className="select full" value={sourceId} onChange={e => setSourceId(e.target.value)}><option value="">Deployment default</option>{sourceConns.map(c => <option key={c.id} value={c.id}>{c.name} · {c.kind}</option>)}</select><div className="muted-2 xs" style={{ marginTop: 4 }}>Schemas and more sources: Settings, after creation.</div></div>
      </div>
      <Label>Review quorum</Label>
      <input id="nd-quorum" className="input" type="number" min={1} value={quorum} onChange={e => setQuorum(Number(e.target.value) || 1)} style={{ width: 100 }} />
      {error && <ErrorNotice error={error} />}
    </Dialog>
  );
}
