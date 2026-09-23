import { useEffect, useMemo, useState } from "react";
import { Button, Glyph, Pill, Skeleton, Spinner } from "@/components/ui";
import { Markdown } from "@/components/Markdown";
import { Icon } from "@/components/icons";
import { Stage, colorFor, type StageEdge, type StageGroup, type StageNode } from "@/components/Stage";
import type { EntityDetail } from "@/api";
import { useApp, useLoad } from "@/state/app";
import { useDomain, useParam } from "@/state/domain";

const DARK = "#1636E0";

export interface ExploreGraph { nodes: Record<string, { id: string; label: string; type: string }>; edges: { from: string; to: string; label: string }[] }
const EMPTY: ExploreGraph = { nodes: {}, edges: [] };

/** Adds an entity and its direct neighbours to the graph; existing nodes keep their place, types are refined. */
/** Lays the overview sample on the canvas (nodes keep their place if already there). */
export function mergeSample(g: ExploreGraph, sample: { nodes: { id: string; label: string; type: string }[]; edges: { from: string; to: string; label: string }[] }): ExploreGraph {
  const nodes = { ...g.nodes };
  for (const n of sample.nodes) nodes[n.id] = { id: n.id, label: n.label, type: n.type || nodes[n.id]?.type || "" };
  const seen = new Set(g.edges.map(x => `${x.from}|${x.label}|${x.to}`));
  const edges = [...g.edges];
  for (const e of sample.edges) { const k = `${e.from}|${e.label}|${e.to}`; if (!seen.has(k)) { seen.add(k); edges.push(e); } }
  return { nodes, edges };
}

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
  // No query and no type: nothing to search for; the overview below is the first picture of the graph.
  const [settled, setSettled] = useState(q);   // the query as typed 350 ms ago: one search per pause, not one per keystroke
  useEffect(() => { const t = setTimeout(() => setSettled(q), 350); return () => clearTimeout(t); }, [q]);
  const results = useLoad(() => (settled.trim() || typeIri) ? api.search(domain.name, settled, { type: typeIri || null, match: (match as "contains" | "exact" | "starts_with") || "contains" }) : Promise.resolve(null), [domain.name, settled, typeIri, match]);
  const entityId = entityParam;   // nothing chosen yet: the canvas shows the overview sample and the panel waits
  const ent = useLoad(() => entityId ? api.entity(domain.name, entityId) : Promise.resolve(null), [domain.name, entityId]);
  const overview = useLoad(() => api.graphOverview(domain.name, 300).catch(() => ({ nodes: [], edges: [] })), [domain.name]);
  const [seeded, setSeeded] = useState("");
  useEffect(() => { setGraph(EMPTY); setExpanded(new Set()); setSeeded(""); }, [domain.name]);   // a new domain starts over
  useEffect(() => { if (overview.data && seeded !== domain.name) { setGraph(g => mergeSample(g, overview.data!)); setSeeded(domain.name); } }, [overview.data, seeded, domain.name]);   // the whole graph first, sampled
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
  // The explanation: the assistant reads the entity through the MCP tools and says what it is, what it links to, and what stands out.
  const [explain, setExplain] = useState<{ id: string; text: string; busy: boolean; error: string | null } | null>(null);
  const explainEntity = async () => {
    if (!e || explain?.busy) return;
    setExplain({ id: e.id, text: "", busy: true, error: null });
    try {
      const r = await api.chat(`Explain ${e.label} (${e.type}): what it is, what it connects to, and what stands out about it. Keep it short.`,
        { domain: domain.name, entity: e.iri, cls: e.type, screen: "explore" }, null, ev => { if (ev.type === "text") setExplain({ id: e.id, text: ev.text, busy: true, error: null }); });
      setExplain({ id: e.id, text: r.answer, busy: false, error: null });
    } catch (err) { setExplain({ id: e.id, text: "", busy: false, error: err instanceof Error ? err.message : String(err) }); }
  };
  const types = useMemo(() => [...new Set(Object.values(graph.nodes).map(n => n.type || "entity"))].sort(), [graph]);
  const groups: StageGroup[] = types.map(t => ({ id: t, label: t, color: colorFor(t) }));
  const nodes: StageNode[] = Object.values(graph.nodes).map(n => ({ id: n.id, label: n.label.length > 30 ? n.label.slice(0, 28) + "…" : n.label, glyph: (n.type || n.label || "?")[0].toUpperCase(), x: 0, y: 0, fill: colorFor(n.type || "entity"), group: n.type || "entity", selected: n.id === entityId }));
  const edges: StageEdge[] = graph.edges.map(x => ({ from: x.from, to: x.to, label: x.label }));
  const shownExplain = explain && explain.id === e?.id ? explain : null;

  return (
    <div className={`xp ${entityId ? "with-panel" : ""}`}>
      <Stage nodes={nodes} edges={edges} height="100%" groups={groups} onSelect={id => setEntity(id)} onExpand={id => expand(id)}
        tools={<><Button size="sm" style={{ height: 28 }} onClick={() => { setGraph(overview.data ? mergeSample(EMPTY, overview.data) : EMPTY); setExpanded(new Set()); }}>Overview</Button><Button size="sm" style={{ height: 28 }} disabled={!e} onClick={() => { setGraph(EMPTY); setExpanded(new Set()); if (e) { setGraph(mergeNeighbourhood(EMPTY, e)); setExpanded(new Set([e.id])); } }}>Just this</Button></>}
        status={busy ? `Expanding ${graph.nodes[busy]?.label ?? busy}…` : overview.loading ? "Sampling the graph…" : `${expanded.size} expanded · click to select, double-click to expand`} />
      <div className="xp-bar">
        <div className="row">
          <h1 style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.02em", lineHeight: 1.15, flex: "none", marginRight: 6 }}>Explore</h1>
          <div className="search-wrap"><Icon name="search" stroke="#7A7A80" /><input id="explore-q" aria-label="Find an entity" className="input" placeholder="Find an entity by label or IRI" value={q} onChange={ev => setQ(ev.target.value)} /></div>
          <select aria-label="Entity type" className="select" value={typeIri} onChange={ev => setTypeIri(ev.target.value)}><option value="">Any type</option>{(status.data?.types ?? []).map(t => <option key={t.iri} value={t.iri}>{t.name} · {t.count.toLocaleString()}</option>)}</select>
          <select aria-label="Match" className="select" value={match} onChange={ev => setMatch(ev.target.value)}><option value="contains">contains</option><option value="exact">exact</option><option value="starts_with">starts with</option></select>
        </div>
        {(results.data?.length || results.data?.length === 0) ? (
          <div className="xp-hits">
            {(results.data ?? []).map(r => <Button key={r.id} size="sm" pill active={r.id === entityId} style={{ height: 26, padding: "0 10px 0 4px", gap: 6 }} onClick={() => { setEntity(r.id); }}><Glyph size={18} fontSize={9}>{r.type[0]}</Glyph>{r.label}<span className="muted-2" style={{ fontWeight: 500 }}>{r.type}</span></Button>)}
            {results.data?.length === 0 && <span className="muted small">No entity matches “{q}”.</span>}
          </div>
        ) : null}
      </div>
      {status.data && <span className="xp-stats mono">{status.data.triples} triples · {status.data.entities} entities</span>}
      {entityId && (
        <aside className="xp-panel" aria-label="Selected entity">
          <div className="xp-panel-head">
            {e ? <><Glyph size={30} fontSize={12}>{e.type[0]}</Glyph><div style={{ minWidth: 0 }}><div style={{ fontSize: 15, fontWeight: 800, lineHeight: 1.2 }}>{e.label}</div><div className="muted" style={{ fontSize: 11.5, fontWeight: 600 }}>{e.type}</div></div></>
              : <div style={{ flex: 1 }}><Skeleton h={30} w={200} /></div>}
            <button type="button" className="xp-close" aria-label="Close the panel" title="Deselect" onClick={() => setEntity("")}>×</button>
          </div>
          <div className="xp-panel-body">
            {ent.loading && !e && <><Skeleton h={14} /><Skeleton h={14} /><Skeleton h={14} /></>}
            {ent.error && !e && <div className="notice error">{ent.error}</div>}
            {e && (
              <>
                <div className="mono" style={{ margin: "0 0 12px", fontSize: 11, color: "var(--muted-2)", wordBreak: "break-all", display: "flex", gap: 6, alignItems: "flex-start" }}><span style={{ flex: 1 }}>{e.iri}</span><button type="button" title="Copy IRI" aria-label="Copy IRI" style={{ border: 0, background: "transparent", color: "var(--muted-2)", cursor: "pointer", padding: 0 }} onClick={() => { navigator.clipboard?.writeText(e.iri).catch(() => {}); say("IRI copied"); }}><Icon name="copy" size={14} /></button></div>
                <div className="row" style={{ gap: 6, marginBottom: 14 }}>
                  <Button size="sm" variant="primary" style={{ flex: 1, height: 30 }} disabled={!!busy} onClick={expandAround}>Expand one more hop</Button>
                  <Button size="sm" style={{ height: 30 }} disabled={!!busy || expanded.has(e.id)} onClick={() => expand(e.id)}>{expanded.has(e.id) ? "Expanded" : "Expand"}</Button>
                  <Button size="sm" style={{ height: 30 }} disabled={!!shownExplain?.busy} onClick={explainEntity}><Icon name="ask" size={13} />Explain</Button>
                </div>
                {shownExplain && (
                  <div className="xp-explain" aria-live="polite">
                    <h3 className="label-caps" style={{ marginBottom: 6 }}>Explanation</h3>
                    {shownExplain.busy && !shownExplain.text && <div className="muted small row" style={{ gap: 8 }}><Spinner blue />Reading the graph…</div>}
                    {shownExplain.error && <div className="notice error">{shownExplain.error}</div>}
                    {shownExplain.text && <Markdown text={shownExplain.text} />}
                  </div>
                )}
                <h3 className="label-caps" style={{ margin: "14px 0 4px" }}>Attributes</h3>
                {e.attrs.map(a => <div key={a.k} style={{ display: "grid", gridTemplateColumns: "1fr 1.3fr", gap: 10, padding: "7px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}><span className="muted">{a.k}</span><span className="row" style={{ gap: 6, minWidth: 0 }}><span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.v}</span><span className="mono muted-3" style={{ fontSize: 10, flex: "none" }}>{a.dt}</span>{a.inferred && <Pill tone="warn" style={{ height: 16, padding: "0 6px", fontSize: 9.5, fontWeight: 700 }}>inferred</Pill>}</span></div>)}
                <h3 className="label-caps" style={{ margin: "16px 0 4px" }}>Outgoing</h3>
                {e.out.map(o => <div key={o.pred} style={{ padding: "7px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}><div style={{ fontWeight: 600, color: DARK, fontSize: 11.5 }}>{o.pred}</div>{o.targets.map(t => <a key={t.id} href="#" style={{ display: "block", padding: "2px 0", color: "var(--ink)" }} onClick={ev => { ev.preventDefault(); setEntity(t.id); }}>{t.label} <span className="muted-2" style={{ fontSize: 11.5 }}>{t.type}</span></a>)}</div>)}
                {e.out.length === 0 && <p className="muted-2 small" style={{ padding: "7px 0" }}>No outgoing relationships.</p>}
                <h3 className="label-caps" style={{ margin: "16px 0 4px" }}>Incoming</h3>
                {e.inc.map(o => <div key={o.pred} style={{ padding: "7px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}><div className="row between" style={{ fontSize: 11.5 }}><span style={{ fontWeight: 600, color: DARK }}>{o.pred}</span><span className="muted-2">{o.count}</span></div>{o.targets.map(t => <a key={t.id} href="#" style={{ display: "block", padding: "2px 0", color: "var(--ink)" }} onClick={ev => { ev.preventDefault(); setEntity(t.id); }}>{t.label} <span className="muted-2" style={{ fontSize: 11.5 }}>{t.type}</span></a>)}{o.targets.length < Number(o.count) && <span className="muted-3 xs" style={{ display: "inline-block", marginTop: 4 }}>showing {o.targets.length} of {o.count}</span>}</div>)}
                {e.inc.length === 0 && <p className="muted-2 small" style={{ padding: "7px 0" }}>No incoming relationships.</p>}
              </>
            )}
          </div>
        </aside>
      )}
    </div>
  );
}
