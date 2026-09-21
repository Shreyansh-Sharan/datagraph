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
            const more = d.schemas.length > 1 ? ` +${d.schemas.length - 1}` : "";
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
  const [error, setError] = useState<string | null>(null);
  const valid = /^[A-Za-z0-9_-]+$/.test(name);
  const create = async () => {
    try { onCreated(await api.createDomain({ name, description, base_iri: baseIri.endsWith("/") ? `${baseIri}${name}/` : baseIri, quorum })); setName(""); setDescription(""); setError(null); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <Dialog title="New domain" open={open} onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!valid} onClick={create}>Create domain</Button></>}>
      <Label>Name</Label>
      <input id="nd-name" className="input mono full" placeholder="hr" value={name} onChange={e => setName(e.target.value)} aria-invalid={!!name && !valid} />
      <div className="muted-2 xs" style={{ margin: "4px 0 12px" }}>Letters, digits, - and _ only.</div>
      <Label>Description</Label>
      <input id="nd-desc" className="input full" placeholder="People and departments" value={description} onChange={e => setDescription(e.target.value)} style={{ marginBottom: 12 }} />
      <Label>Base IRI</Label>
      <input id="nd-iri" className="input mono full" value={baseIri} onChange={e => setBaseIri(e.target.value)} style={{ marginBottom: 12 }} />
      <Label>Review quorum</Label>
      <input id="nd-quorum" className="input" type="number" min={1} value={quorum} onChange={e => setQuorum(Number(e.target.value) || 1)} style={{ width: 100 }} />
      {error && <ErrorNotice error={error} />}
    </Dialog>
  );
}
