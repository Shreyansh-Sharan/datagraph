import { useEffect, useMemo, useState } from "react";
import { Button, Card, Glyph, Pill, Skeleton } from "@/components/ui";
import { Icon } from "@/components/icons";
import { Stage, colorFor, type StageEdge, type StageGroup, type StageNode } from "@/components/Stage";
import type { EntityDetail } from "@/api";
import { useApp, useLoad } from "@/state/app";
import { useDomain, useParam } from "@/state/domain";

const BLUE = "#2249FF", DARK = "#1636E0";

export interface ExploreGraph { nodes: Record<string, { id: string; label: string; type: string }>; edges: { from: string; to: string; label: string }[] }
const EMPTY: ExploreGraph = { nodes: {}, edges: [] };

/** Adds an entity and its direct neighbours to the graph; existing nodes keep their place, types are refined. */
export function mergeNeighbourhood(g: ExploreGraph, e: EntityDetail): ExploreGraph {
  const nodes = { ...g.nodes, [e.id]: { id: e.id, label: e.label, type: e.type || g.nodes[e.id]?.type || "" } };
  const seen = new Set(g.edges.map(x => `${x.from}|${x.label}|${x.to}`));
  const edges = [...g.edges];
  const add = (from: string, to: string, label: string) => { const k = `${from}|${label}|${to}`; if (!seen.has(k)) { seen.add(k); edges.push({ from, to, label }); } };
  for (const o of e.out) for (const t of o.targets) { nodes[t.id] = { id: t.id, label: t.label, type: t.type || nodes[t.id]?.type || "" }; add(e.id, t.id, o.pred); }
  for (const o of e.inc) for (const t of o.targets) { nodes[t.id] = { id: t.id, label: t.label, type: t.type || nodes[t.id]?.type || "" }; add(t.id, e.id, o.pred); }
  return { nodes, edges };
}

export function Explore() {
  const { api, say } = useApp();
  const { domain } = useDomain();
  const [q, setQ] = useParam("q", "");
  const [typeIri, setTypeIri] = useParam("type", "");
  const [match, setMatch] = useParam("match", "contains");
  const [entityParam, setEntity] = useParam("entity", "");
  const [graph, setGraph] = useState<ExploreGraph>(EMPTY);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const status = useLoad(() => api.graphStatus(domain.name), [domain.name]);
  const results = useLoad(() => api.search(domain.name, q, { type: typeIri || null, match: (match as "contains" | "exact" | "starts_with") || "contains" }), [domain.name, q, typeIri, match]);
  const entityId = entityParam || results.data?.[0]?.id || "";   // nothing chosen yet: start from the first match
  const ent = useLoad(() => entityId ? api.entity(domain.name, entityId) : Promise.resolve(null), [domain.name, entityId]);
  useEffect(() => { setGraph(EMPTY); setExpanded(new Set()); }, [domain.name]);   // a new domain starts an empty canvas
  // The selected entity's neighbourhood joins the graph the first time it is opened, or when it is expanded.
  useEffect(() => { const e = ent.data; if (!e) return; setGraph(g => (g.nodes[e.id] && expanded.has(e.id) ? g : mergeNeighbourhood(g, e))); setExpanded(x => (x.has(e.id) ? x : new Set(x).add(e.id))); }, [ent.data]);   // eslint-disable-line react-hooks/exhaustive-deps
  const expand = async (id: string) => {
    if (busy) return; setBusy(id);
    try { const e = await api.entity(domain.name, id); setGraph(g => mergeNeighbourhood(g, e)); setExpanded(x => new Set(x).add(id)); say(`${e.label}: ${e.out.reduce((a, o) => a + o.targets.length, 0) + e.inc.reduce((a, o) => a + o.targets.length, 0)} neighbours added`); }
    catch (err) { say(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(null); }
  };
  const expandAround = async () => {   // one more hop around the selected entity, a few at a time
    const around = graph.edges.filter(x => x.from === entityId || x.to === entityId).map(x => (x.from === entityId ? x.to : x.from)).filter(id => !expanded.has(id)).slice(0, 12);
    for (const id of around) await expand(id);
  };


  const e = ent.data;
  const types = useMemo(() => [...new Set(Object.values(graph.nodes).map(n => n.type || "entity"))].sort(), [graph]);
  const groups: StageGroup[] = types.map(t => ({ id: t, label: t, color: colorFor(t) }));
  const nodes: StageNode[] = Object.values(graph.nodes).map(n => ({ id: n.id, label: n.label.length > 30 ? n.label.slice(0, 28) + "…" : n.label, glyph: (n.type || n.label || "?")[0].toUpperCase(), x: 0, y: 0, fill: colorFor(n.type || "entity"), border: n.id === entityId ? BLUE : undefined, selected: n.id === entityId, group: n.type || "entity", title: expanded.has(n.id) ? "expanded" : "double-click to expand" }));
  const edges: StageEdge[] = graph.edges.map(x => ({ from: x.from, to: x.to, label: x.label }));

  return (
    <>
      <div className="row" style={{ gap: 12, marginBottom: 16 }}>
        <h1 style={{ fontSize: 28, fontWeight: 800, letterSpacing: "-.02em", lineHeight: 1.15, flex: "none" }}>Explore</h1>
        <div className="row" style={{ flex: 1, maxWidth: 760, marginLeft: 16 }}>
          <div className="search-wrap"><Icon name="search" stroke="#7A7A80" /><input id="explore-q" aria-label="Find an entity" className="input" placeholder="Find an entity by label or IRI" value={q} onChange={ev => setQ(ev.target.value)} /></div>
          <select aria-label="Entity type" className="select" value={typeIri} onChange={ev => setTypeIri(ev.target.value)}><option value="">Any type</option>{(status.data?.types ?? []).map(t => <option key={t.iri} value={t.iri}>{t.name} · {t.count.toLocaleString()}</option>)}</select>
          <select aria-label="Match" className="select" value={match} onChange={ev => setMatch(ev.target.value)}><option value="contains">contains</option><option value="exact">exact</option><option value="starts_with">starts with</option></select>
        </div>
        <span className="mono muted small" style={{ marginLeft: "auto" }}>{status.data ? `${status.data.triples} triples · ${status.data.entities} entities` : ""}</span>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 12, minHeight: 26 }}>
        {(results.data ?? []).map(r => <Button key={r.id} size="sm" pill active={r.id === entityId} style={{ height: 26, padding: "0 10px 0 4px", gap: 6 }} onClick={() => { setEntity(r.id); }}><Glyph size={18} fontSize={9}>{r.type[0]}</Glyph>{r.label}<span className="muted-2" style={{ fontWeight: 500 }}>{r.type}</span></Button>)}
        {results.data?.length === 0 && <span className="muted small">No entity matches “{q}”.</span>}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 360px", gap: 20, alignItems: "start" }}>
        <Stage nodes={nodes} edges={edges} height={640} groups={groups} onSelect={id => setEntity(id)} onExpand={id => expand(id)}
          tools={<Button size="sm" style={{ height: 28 }} onClick={() => { setGraph(EMPTY); setExpanded(new Set()); if (e) { setGraph(mergeNeighbourhood(EMPTY, e)); setExpanded(new Set([e.id])); } }}>Clear</Button>}
          status={busy ? `Expanding ${graph.nodes[busy]?.label ?? busy}…` : e ? `${expanded.size} expanded · click to select, double-click to expand` : "Pick an entity to start"} />
        <Card style={{ maxHeight: 560, overflow: "auto" }}>
          {ent.loading && !e && <><Skeleton h={30} w={200} /><Skeleton h={14} style={{ marginTop: 10 }} /><Skeleton h={14} /></>}
          {e && (
            <>
              <div className="row" style={{ gap: 10 }}><Glyph size={30} fontSize={12}>{e.type[0]}</Glyph><div><div style={{ fontSize: 15, fontWeight: 800, lineHeight: 1.2 }}>{e.label}</div><div className="muted" style={{ fontSize: 11.5, fontWeight: 600 }}>{e.type}</div></div></div>
              <div className="mono" style={{ margin: "10px 0 14px", fontSize: 11, color: "var(--muted-2)", wordBreak: "break-all", display: "flex", gap: 6, alignItems: "flex-start" }}><span style={{ flex: 1 }}>{e.iri}</span><button type="button" title="Copy IRI" aria-label="Copy IRI" style={{ border: 0, background: "transparent", color: "var(--muted-2)", cursor: "pointer", padding: 0 }} onClick={() => { navigator.clipboard?.writeText(e.iri).catch(() => {}); say("IRI copied"); }}><Icon name="copy" size={14} /></button></div>
              <div className="row" style={{ gap: 6, marginBottom: 16 }}><Button size="sm" variant="primary" style={{ flex: 1, height: 30 }} disabled={!!busy} onClick={expandAround}>Expand one more hop</Button><Button size="sm" style={{ height: 30 }} disabled={!!busy || expanded.has(e.id)} onClick={() => expand(e.id)}>{expanded.has(e.id) ? "Expanded" : "Expand"}</Button></div>
              <h3 className="label-caps" style={{ marginBottom: 4 }}>Attributes</h3>
              {e.attrs.map(a => <div key={a.k} style={{ display: "grid", gridTemplateColumns: "1fr 1.3fr", gap: 10, padding: "7px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}><span className="muted">{a.k}</span><span className="row" style={{ gap: 6, minWidth: 0 }}><span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.v}</span><span className="mono muted-3" style={{ fontSize: 10, flex: "none" }}>{a.dt}</span>{a.inferred && <Pill tone="warn" style={{ height: 16, padding: "0 6px", fontSize: 9.5, fontWeight: 700 }}>inferred</Pill>}</span></div>)}
              <h3 className="label-caps" style={{ margin: "16px 0 4px" }}>Outgoing</h3>
              {e.out.map(o => <div key={o.pred} style={{ padding: "7px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}><div style={{ fontWeight: 600, color: DARK, fontSize: 11.5 }}>{o.pred}</div>{o.targets.map(t => <a key={t.id} href="#" style={{ display: "block", padding: "2px 0", color: "var(--ink)" }} onClick={ev => { ev.preventDefault(); setEntity(t.id); }}>{t.label} <span className="muted-2" style={{ fontSize: 11.5 }}>{t.type}</span></a>)}</div>)}
              {e.out.length === 0 && <p className="muted-2 small" style={{ padding: "7px 0" }}>No outgoing relationships.</p>}
              <h3 className="label-caps" style={{ margin: "16px 0 4px" }}>Incoming</h3>
              {e.inc.map(o => <div key={o.pred} style={{ padding: "7px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}><div className="row between" style={{ fontSize: 11.5 }}><span style={{ fontWeight: 600, color: DARK }}>{o.pred}</span><span className="muted-2">{o.count}</span></div>{o.targets.map(t => <a key={t.id} href="#" style={{ display: "block", padding: "2px 0", color: "var(--ink)" }} onClick={ev => { ev.preventDefault(); setEntity(t.id); }}>{t.label} <span className="muted-2" style={{ fontSize: 11.5 }}>{t.type}</span></a>)}<a href="#" className="small" style={{ display: "inline-block", marginTop: 4, fontWeight: 600 }} onClick={ev => { ev.preventDefault(); say("Loading 20 more…"); }}>Show 20 more</a></div>)}
            </>
          )}
        </Card>
      </div>
    </>
  );
}
