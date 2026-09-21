import { useState } from "react";
import { Button, Card, Dot, Glyph, Pill, Skeleton } from "@/components/ui";
import { Icon } from "@/components/icons";
import { Stage, colorFor, type StageEdge, type StageNode } from "@/components/Stage";
import { useApp, useLoad } from "@/state/app";
import { useDomain, useParam } from "@/state/domain";

const BLUE = "#2249FF", DARK = "#1636E0";

export function Explore() {
  const { api, say } = useApp();
  const { domain } = useDomain();
  const [q, setQ] = useParam("q", "");
  const [entityParam, setEntity] = useParam("entity", "");
  const [depth, setDepth] = useState(1);
  const status = useLoad(() => api.graphStatus(domain.name), [domain.name]);
  const results = useLoad(() => api.search(domain.name, q), [domain.name, q]);
  const entityId = entityParam || results.data?.[0]?.id || "";   // nothing chosen yet: start from the first match
  const ent = useLoad(() => entityId ? api.entity(domain.name, entityId) : Promise.resolve(null), [domain.name, entityId]);


  const e = ent.data;
  const neigh = e ? [...e.out.flatMap(o => o.targets.map(t => ({ p: o.pred, t, far: false }))), ...e.inc.flatMap(o => o.targets.map(t => ({ p: o.pred, t, far: false }))), ...(depth > 1 ? e.far.map(f => ({ p: f.pred, t: f.target, far: true })) : [])] : [];
  const placed = neigh.map((n, i) => { const ang = (i / Math.max(1, neigh.length)) * Math.PI * 2 - Math.PI / 2; const r = n.far ? 42 : 28; return { ...n, x: 50 + r * Math.cos(ang) * 1.15, y: 50 + r * Math.sin(ang) }; });
  const nodes: StageNode[] = e ? [{ id: "__center", label: e.label, glyph: e.type[0], x: 50, y: 50, fill: colorFor(e.type), border: BLUE, selected: true, size: "lg", pin: true }, ...placed.map(n => ({ id: n.t.id, label: n.t.label.length > 26 ? n.t.label.slice(0, 24) + "…" : n.t.label, glyph: (n.t.type || n.t.label || "?")[0].toUpperCase(), x: n.x, y: n.y, fill: colorFor(n.t.type || e.type), border: "#D4DCFF", size: "sm" as const }))] : [];
  const edges: StageEdge[] = placed.map(n => ({ from: "__center", to: n.t.id, label: n.p, color: "#8FA1FF", labelColor: "#5F5F60" }));
  const legend = e ? [[e.type, colorFor(e.type)], ...[...new Set(neigh.map(n => n.t.type).filter(Boolean))].slice(0, 5).map(t => [t, colorFor(t)] as [string, string])] : [];

  return (
    <>
      <div className="row" style={{ gap: 12, marginBottom: 16 }}>
        <h1 style={{ fontSize: 28, fontWeight: 800, letterSpacing: "-.02em", lineHeight: 1.15, flex: "none" }}>Explore</h1>
        <div className="row" style={{ flex: 1, maxWidth: 760, marginLeft: 16 }}>
          <div className="search-wrap"><Icon name="search" stroke="#7A7A80" /><input id="explore-q" aria-label="Find an entity" className="input" placeholder="Find an entity by label or IRI" value={q} onChange={ev => setQ(ev.target.value)} /></div>
          <select aria-label="Entity type" className="select"><option>Any type</option><option>Customer</option><option>Product</option><option>Sale</option></select>
          <select aria-label="Match" className="select"><option>contains</option><option>exact</option><option>starts</option></select>
        </div>
        <span className="mono muted small" style={{ marginLeft: "auto" }}>{status.data ? `${status.data.triples} triples · ${status.data.entities} entities` : ""}</span>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 12, minHeight: 26 }}>
        {(results.data ?? []).map(r => <Button key={r.id} size="sm" pill active={r.id === entityId} style={{ height: 26, padding: "0 10px 0 4px", gap: 6 }} onClick={() => { setEntity(r.id); setDepth(1); }}><Glyph size={18} fontSize={9}>{r.type[0]}</Glyph>{r.label}<span className="muted-2" style={{ fontWeight: 500 }}>{r.type}</span></Button>)}
        {results.data?.length === 0 && <span className="muted small">No entity matches “{q}”.</span>}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 360px", gap: 20, alignItems: "start" }}>
        <Stage nodes={nodes} edges={edges} height={560} onSelect={id => { if (id !== "__center") { setEntity(id); setDepth(1); } }}
          tools={<><select aria-label="Colour by" className="select" style={{ height: 28, fontSize: 11.5, color: "var(--muted)", borderColor: "var(--line)" }}><option>Colour by class</option><option>Colour by community</option></select></>}
          legend={legend.map(([l, c]) => <span key={l}><Dot color={c} size={9} />{l}</span>)}
          status={e ? `${nodes.length - 1} neighbour${nodes.length === 2 ? "" : "s"} of ${e.label}` : "Pick an entity to see its neighbourhood"}>
        </Stage>
        <Card style={{ maxHeight: 560, overflow: "auto" }}>
          {ent.loading && !e && <><Skeleton h={30} w={200} /><Skeleton h={14} style={{ marginTop: 10 }} /><Skeleton h={14} /></>}
          {e && (
            <>
              <div className="row" style={{ gap: 10 }}><Glyph size={30} fontSize={12}>{e.type[0]}</Glyph><div><div style={{ fontSize: 15, fontWeight: 800, lineHeight: 1.2 }}>{e.label}</div><div className="muted" style={{ fontSize: 11.5, fontWeight: 600 }}>{e.type}</div></div></div>
              <div className="mono" style={{ margin: "10px 0 14px", fontSize: 11, color: "var(--muted-2)", wordBreak: "break-all", display: "flex", gap: 6, alignItems: "flex-start" }}><span style={{ flex: 1 }}>{e.iri}</span><button type="button" title="Copy IRI" aria-label="Copy IRI" style={{ border: 0, background: "transparent", color: "var(--muted-2)", cursor: "pointer", padding: 0 }} onClick={() => { navigator.clipboard?.writeText(e.iri).catch(() => {}); say("IRI copied"); }}><Icon name="copy" size={14} /></button></div>
              <div className="row" style={{ gap: 6, marginBottom: 16 }}><Button size="sm" variant="primary" style={{ flex: 1, height: 30 }} onClick={() => setDepth(d => (d >= 2 ? 1 : 2))}>Expand depth {depth}</Button><Button size="sm" style={{ height: 30 }} onClick={() => say(`Focused on ${e.label}`)}>Focus</Button></div>
              <h3 className="label-caps" style={{ marginBottom: 4 }}>Attributes</h3>
              {e.attrs.map(a => <div key={a.k} style={{ display: "grid", gridTemplateColumns: "1fr 1.3fr", gap: 10, padding: "7px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}><span className="muted">{a.k}</span><span className="row" style={{ gap: 6, minWidth: 0 }}><span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.v}</span><span className="mono muted-3" style={{ fontSize: 10, flex: "none" }}>{a.dt}</span>{a.inferred && <Pill tone="warn" style={{ height: 16, padding: "0 6px", fontSize: 9.5, fontWeight: 700 }}>inferred</Pill>}</span></div>)}
              <h3 className="label-caps" style={{ margin: "16px 0 4px" }}>Outgoing</h3>
              {e.out.map(o => <div key={o.pred} style={{ padding: "7px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}><div style={{ fontWeight: 600, color: DARK, fontSize: 11.5 }}>{o.pred}</div>{o.targets.map(t => <a key={t.id} href="#" style={{ display: "block", padding: "2px 0", color: "var(--ink)" }} onClick={ev => { ev.preventDefault(); setEntity(t.id); setDepth(1); }}>{t.label} <span className="muted-2" style={{ fontSize: 11.5 }}>{t.type}</span></a>)}</div>)}
              {e.out.length === 0 && <p className="muted-2 small" style={{ padding: "7px 0" }}>No outgoing relationships.</p>}
              <h3 className="label-caps" style={{ margin: "16px 0 4px" }}>Incoming</h3>
              {e.inc.map(o => <div key={o.pred} style={{ padding: "7px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}><div className="row between" style={{ fontSize: 11.5 }}><span style={{ fontWeight: 600, color: DARK }}>{o.pred}</span><span className="muted-2">{o.count}</span></div>{o.targets.map(t => <a key={t.id} href="#" style={{ display: "block", padding: "2px 0", color: "var(--ink)" }} onClick={ev => { ev.preventDefault(); setEntity(t.id); setDepth(1); }}>{t.label} <span className="muted-2" style={{ fontSize: 11.5 }}>{t.type}</span></a>)}<a href="#" className="small" style={{ display: "inline-block", marginTop: 4, fontWeight: 600 }} onClick={ev => { ev.preventDefault(); say("Loading 20 more…"); }}>Show 20 more</a></div>)}
            </>
          )}
        </Card>
      </div>
    </>
  );
}
