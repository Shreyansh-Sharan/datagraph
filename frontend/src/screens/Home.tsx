import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Card, Dialog, Dot, ErrorNotice, Label, Skeleton } from "@/components/ui";
import { useApp, useLoad } from "@/state/app";
import { Ask } from "./Ask";
import type { DomainSummary } from "@/api";

export function Home() {
  const { api, config, say } = useApp();
  const navigate = useNavigate();
  const { data, error, loading, reload } = useLoad(() => api.domains(), []);
  const [dialog, setDialog] = useState(false);
  const dbx = config.sourceKind === "databricks";
  const open = (d: DomainSummary, screen = "") => navigate(`/d/${encodeURIComponent(d.name)}${screen ? `/${screen}` : ""}`);

  return (
    <>
      <Ask domains={data ?? undefined} />
      <div style={{ maxWidth: 960, margin: "0 auto" }}>
        <div className="row between" style={{ alignItems: "flex-end", gap: 16, margin: "8px 0 12px" }}>
          <div><h2 style={{ fontSize: 18, fontWeight: 800, letterSpacing: "-.01em", marginBottom: 2 }}>Domains</h2><p className="muted" style={{ fontSize: 12.5 }}>One knowledge graph each, with its own source, versions, review quorum and MCP policy. Open one to work in it.</p></div>
          <div className="row" style={{ flex: "none" }}><Button size="sm" style={{ height: 32 }} onClick={() => say("Choose a bundle file to import")}>Import bundle</Button><Button size="sm" variant="primary" style={{ height: 32 }} onClick={() => setDialog(true)}>New domain</Button></div>
        </div>
        {error && <ErrorNotice error={error} action={<Button size="sm" onClick={reload}>Retry</Button>} />}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(280px,1fr))", gap: 14 }}>
          {loading && [0, 1, 2].map(i => <Card key={i}><Skeleton h={34} w={160} /><Skeleton h={16} style={{ marginTop: 14 }} /><Skeleton h={16} /><Skeleton h={16} /></Card>)}
          {data?.map(d => {
            const act = d.versions.find(v => v.active); const dr = d.versions.find(v => v.status === "draft");
            const state = act ? `v${act.version} active` : dr ? `v${dr.version} draft` : "no version";
            const dot = act ? "var(--blue)" : dr ? "var(--grey)" : "var(--grey-2)";
            const more = d.sources.length > 1 ? ` +${d.sources.length - 1} source${d.sources.length > 2 ? "s" : ""}` : d.schemas.length > 1 ? ` +${d.schemas.length - 1}` : "";
            const cfg = [["Source", dbx ? `databricks · ${d.catalog}.${d.schema}${more}` : `postgres · ${d.catalog}_${d.schema}${more}`], ["Base IRI", d.base_iri], ["Review quorum", String(d.quorum)], ["MCP", d.mcpExposed ? `exposed · ${d.disabledTools.length} tools off` : "hidden"]];
            return (
              <Card key={d.name} style={{ borderRadius: 12, display: "flex", flexDirection: "column", gap: 12 }}>
                <div className="row between" style={{ gap: 10 }}>
                  <a href="#" onClick={e => { e.preventDefault(); open(d); }} style={{ display: "flex", alignItems: "center", gap: 10, color: "var(--ink)", minWidth: 0 }}>
                    <span style={{ width: 34, height: 34, borderRadius: 9, background: "var(--blue-soft)", color: "var(--blue)", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 900, flex: "none" }}>{d.name[0].toUpperCase()}</span>
                    <span style={{ minWidth: 0 }}><span style={{ display: "block", fontSize: 16, fontWeight: 800, color: "var(--blue)" }}>{d.name}</span><span className="muted" style={{ display: "block", fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.description}</span></span>
                  </a>
                  <span className="pill lg" style={{ flex: "none" }}><Dot color={dot} />{state}</span>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 8 }}>
                  {[["Triples", d.triples], ["Versions", String(d.versions.length)], ["Last build", d.lastBuild]].map(([k, v]) => <div key={k}><div className="label-caps" style={{ fontSize: 10.5, color: "var(--muted-3)" }}>{k}</div><div style={{ fontSize: 16, fontWeight: 800, letterSpacing: "-.02em" }}>{v}</div></div>)}
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
      </div>
      <NewDomainDialog open={dialog} onClose={() => setDialog(false)} onCreated={d => { setDialog(false); say(`Domain ${d.name} created`); open(d); }} />
    </>
  );
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
