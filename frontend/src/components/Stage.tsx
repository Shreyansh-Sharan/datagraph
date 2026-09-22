// The node-link stage, drawn the way graph browsers draw graphs and read the way analysts read
// them: the whole graph first (bubbles sized and labelled by how connected they are, coloured by
// group, with the groups as toggles), then drill-down: click a node to spotlight its neighbourhood,
// double-click to expand it, ◎ to isolate it, search to jump to it. React Flow is the canvas,
// d3-force places the nodes (dagre is the alternative ranked layout).
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Background, BackgroundVariant, BaseEdge, EdgeLabelRenderer, Handle, MarkerType, MiniMap, Position, ReactFlow, ReactFlowProvider, getStraightPath, useEdgesState, useInternalNode, useNodesState, useReactFlow, type Edge, type EdgeProps, type Node, type NodeProps } from "@xyflow/react";
import dagre from "@dagrejs/dagre";
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY } from "d3-force";

export interface StageNode { id: string; label: string; glyph: string; x: number; y: number; fill: string; border?: string; selected?: boolean; props?: number; title?: string; size?: "md" | "sm" | "lg"; pin?: boolean; group?: string }
export interface StageEdge { from: string; to: string; label: string; color?: string; dashed?: boolean; width?: number; labelColor?: string }
export interface StageGroup { id: string; label: string; color: string }
export type StageLayout = "force" | "dagre" | "given";
type Direction = "TB" | "LR";

const GIVEN_WIDTH = 1100;   // virtual canvas for percentage positions

/** A stable colour per class name, the way graph browsers colour labels. */
const PALETTE = ["#4C8EDA", "#57C7E3", "#F16667", "#8DCC93", "#ECB5C9", "#FFC454", "#DA7194", "#569480", "#C990C0", "#F79767", "#A5ABB6", "#D9C8AE"];
export function colorFor(name: string): string {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

/** Bubble radius: an explicit size wins, otherwise the more connected, the bigger (16 to 40 px). */
export function radiusFor(n: StageNode, degree: number): number {
  if (n.size === "lg") return 38;
  if (n.size === "sm") return 20;
  if (n.size === "md") return 30;
  return Math.round(Math.min(40, 16 + Math.sqrt(degree) * 6));
}

export function degrees(nodes: StageNode[], edges: StageEdge[]): Record<string, number> {
  const d: Record<string, number> = Object.fromEntries(nodes.map(n => [n.id, 0]));
  for (const e of edges) { if (e.from in d) d[e.from]++; if (e.to in d) d[e.to]++; }
  return d;
}

/** Node centres. Force: a settled d3 simulation, deterministic for the same input. */
export function layoutNodes(nodes: StageNode[], edges: StageEdge[], layout: StageLayout, direction: Direction, height: number): Record<string, { x: number; y: number }> {
  if (layout === "given") return Object.fromEntries(nodes.map(n => [n.id, { x: (n.x / 100) * GIVEN_WIDTH, y: (n.y / 100) * Math.max(height, 400) }]));
  const ids = new Set(nodes.map(n => n.id));
  const links = edges.filter(e => ids.has(e.from) && ids.has(e.to) && e.from !== e.to);
  const deg = degrees(nodes, edges);
  const radius = (n: StageNode) => radiusFor(n, deg[n.id] ?? 0);
  if (layout === "dagre") {
    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: direction, nodesep: 30, ranksep: direction === "TB" ? 70 : 100, marginx: 8, marginy: 8, ranker: "tight-tree" });
    g.setDefaultEdgeLabel(() => ({}));
    for (const n of nodes) g.setNode(n.id, { width: radius(n) * 2, height: radius(n) * 2 });
    for (const e of links) g.setEdge(e.from, e.to);
    dagre.layout(g);
    return Object.fromEntries(nodes.map(n => { const p = g.node(n.id); return [n.id, { x: p.x, y: p.y }]; }));
  }
  // force: start on a deterministic ring so the same graph always settles the same way
  type Sim = { id: string; r: number; x: number; y: number; fx?: number; fy?: number };
  const count = nodes.length || 1;
  const sim: Sim[] = nodes.map((node, i) => { const a = (i / count) * Math.PI * 2, r = 60 + Math.sqrt(count) * 28; return { id: node.id, r: radius(node), x: node.pin ? 0 : Math.cos(a) * r, y: node.pin ? 0 : Math.sin(a) * r, fx: node.pin ? 0 : undefined, fy: node.pin ? 0 : undefined }; });
  const byId = new Map(sim.map(s => [s.id, s]));
  const simulation = forceSimulation<Sim>(sim)
    .force("link", forceLink<Sim, { source: string; target: string }>(links.map(e => ({ source: e.from, target: e.to }))).id(d => d.id)
      .distance(l => 60 + (byId.get(typeof l.source === "string" ? l.source : (l.source as Sim).id)?.r ?? 30) + (byId.get(typeof l.target === "string" ? l.target : (l.target as Sim).id)?.r ?? 30)).strength(0.5))
    .force("charge", forceManyBody().strength(-380))
    .force("collide", forceCollide<Sim>().radius(d => d.r + 16).strength(0.9))
    .force("x", forceX(0).strength(0.04)).force("y", forceY(0).strength(0.04))
    .force("center", forceCenter(0, 0))
    .stop();
  for (let i = 0; i < 300; i++) simulation.tick();
  return Object.fromEntries(sim.map(s => [s.id, { x: s.x, y: s.y }]));
}

type BubbleData = { node: StageNode; r: number; dim: boolean; showName: boolean; onSelect?: (id: string) => void; onExpand?: (id: string) => void };

function Bubble({ data }: NodeProps<Node<BubbleData>>) {
  const { node: n, dim, showName, onSelect, onExpand } = data;
  const r = Number.isFinite(data.r) && data.r > 0 ? data.r : 30;   // a node kept across a hot reload may lack it
  const max = Math.max(3, Math.floor(r / 2.6));
  const short = n.label.length > max ? n.label.slice(0, Math.max(2, max - 1)) + "…" : n.label;
  const inside = r >= 24;
  return (
    <>
      <Handle type="target" position={Position.Top} className="stage-handle" />
      <button type="button" className={`bubble ${n.selected ? "selected" : ""} ${dim ? "dim" : ""}`} title={`${n.label}${n.title ? ` · ${n.title}` : ""} · double-click to expand`} aria-label={n.label} aria-pressed={n.selected}
        onClick={() => onSelect?.(n.id)} onDoubleClick={() => onExpand?.(n.id)}
        style={{ width: r * 2, height: r * 2, background: n.fill, borderColor: n.border ?? "rgba(0,0,0,.12)", fontSize: Math.max(9, Math.min(13, r / 2.6)) }}>
        {inside && <span className="cap">{short}</span>}
        {n.props !== undefined && r >= 20 && <span className="props" aria-hidden="true">{n.props}</span>}
        {showName && (!inside || short !== n.label) && <span className="name" aria-hidden="true" style={{ fontSize: Math.max(9.5, Math.min(13, 8 + r / 4)) }}>{n.label}</span>}
      </button>
      <Handle type="source" position={Position.Bottom} className="stage-handle" />
    </>
  );
}
const NODE_TYPES = { bubble: Bubble };

/** Edges leave and enter bubbles on the line between their centres, as in graph browsers. */
function FloatingEdge({ id, source, target, markerEnd, style, label, labelStyle, labelBgStyle }: EdgeProps) {
  const s = useInternalNode(source), t = useInternalNode(target);
  if (!s || !t) return null;
  const c = (n: NonNullable<typeof s>) => ({ x: n.internals.positionAbsolute.x + (n.measured.width ?? 60) / 2, y: n.internals.positionAbsolute.y + (n.measured.height ?? 60) / 2, r: (n.measured.width ?? 60) / 2 });
  const a = c(s), b = c(t);
  const dx = b.x - a.x, dy = b.y - a.y, d = Math.max(1, Math.hypot(dx, dy));
  const ux = dx / d, uy = dy / d;
  const sx = a.x + ux * (a.r + 2), sy = a.y + uy * (a.r + 2), tx = b.x - ux * (b.r + 6), ty = b.y - uy * (b.r + 6);
  const [path] = getStraightPath({ sourceX: sx, sourceY: sy, targetX: tx, targetY: ty });
  const lx = sx + (tx - sx) * 0.62, ly = sy + (ty - sy) * 0.62;   // nearer the target: labels around a hub spread out instead of piling up
  const fill = (labelStyle as { fill?: string } | undefined)?.fill, bg = (labelBgStyle as { fill?: string } | undefined)?.fill;
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} />
      {label && <EdgeLabelRenderer><div className="stage-edge-label" style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)`, color: fill, background: bg, opacity: (style as { opacity?: number } | undefined)?.opacity }}>{label}</div></EdgeLabelRenderer>}
    </>
  );
}
const EDGE_TYPES = { floating: FloatingEdge };

function Tools({ extra, onRelayout, layoutName, focus, nodes, onFind }: { extra?: ReactNode; onRelayout?: () => void; layoutName: string; focus?: { on: boolean; toggle: () => void }; nodes: StageNode[]; onFind?: (id: string) => void }) {
  const flow = useReactFlow();
  const [q, setQ] = useState("");
  const find = (text: string) => {
    const t = text.trim().toLowerCase(); if (!t) return;
    const hit = nodes.find(n => n.label.toLowerCase() === t) ?? nodes.find(n => n.label.toLowerCase().startsWith(t)) ?? nodes.find(n => n.label.toLowerCase().includes(t));
    if (!hit) return;
    onFind?.(hit.id);
    const el = flow.getNodes().find(n => n.id === hit.id);
    if (el) flow.setCenter(el.position.x + (el.measured?.width ?? 40) / 2, el.position.y + (el.measured?.height ?? 40) / 2, { zoom: Math.max(flow.getZoom(), 1), duration: 300 });
  };
  return (
    <div className="stage-tools">
      {onFind && <><input className="input sm mono" list="stage-find" aria-label="Find a node" placeholder="Find…" value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => { if (e.key === "Enter") find(q); }} style={{ height: 28, width: 150 }} />
        <datalist id="stage-find">{nodes.slice(0, 300).map(n => <option key={n.id} value={n.label} />)}</datalist></>}
      {focus && <button type="button" className={focus.on ? "active" : ""} title={focus.on ? "Show every node" : "Isolate the selected node and its neighbours"} aria-label={focus.on ? "Show all" : "Focus on selection"} aria-pressed={focus.on} onClick={focus.toggle}>◎</button>}
      <button type="button" title="Zoom in" aria-label="Zoom in" onClick={() => flow.zoomIn()}>+</button>
      <button type="button" title="Zoom out" aria-label="Zoom out" onClick={() => flow.zoomOut()}>−</button>
      <button type="button" title="Fit" aria-label="Fit" onClick={() => flow.fitView({ padding: 0.12, duration: 300 })}>⤢</button>
      {onRelayout && <button type="button" title={`Layout: ${layoutName} · click to change`} aria-label="Switch layout" onClick={onRelayout}>↻</button>}
      {extra}
    </div>
  );
}

const LAYOUTS: { layout: StageLayout; direction: Direction; name: string }[] = [{ layout: "force", direction: "TB", name: "force" }, { layout: "dagre", direction: "TB", name: "ranked, top to bottom" }, { layout: "dagre", direction: "LR", name: "ranked, left to right" }];

function StageInner({ nodes: givenNodes, edges: givenEdges, height, dotted, onSelect, onExpand, legend, groups, tools, status, children, layout: fixedLayout, spotlight = true }: StageProps) {
  const [step, setStep] = useState(0);
  const chosen = fixedLayout === "given" ? { layout: "given" as const, direction: "TB" as const, name: "given" } : LAYOUTS[step % LAYOUTS.length];
  const [focused, setFocused] = useState(false);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const flow = useReactFlow();
  // group toggles remove whole groups from the overview
  const allNodes = useMemo(() => (hidden.size ? givenNodes.filter(n => !n.group || !hidden.has(n.group)) : givenNodes), [givenNodes, hidden]);
  const allIds = useMemo(() => new Set(allNodes.map(n => n.id)), [allNodes]);
  const allEdges = useMemo(() => givenEdges.filter(e => allIds.has(e.from) && allIds.has(e.to)), [givenEdges, allIds]);
  const selectedId = allNodes.find(n => n.selected)?.id;
  const spotId = spotlight ? selectedId : undefined;   // a preselected node does not dim the overview; a clicked one does
  const neighbours = useMemo(() => { const s = new Set<string>(); if (selectedId === undefined) return s; s.add(selectedId); for (const e of allEdges) { if (e.from === selectedId) s.add(e.to); if (e.to === selectedId) s.add(e.from); } return s; }, [allEdges, selectedId]);
  const hasNeighbours = neighbours.size > 1;
  const focusOn = focused && chosen.layout !== "given" && selectedId !== undefined && hasNeighbours;
  const { nodes, edges } = useMemo(() => focusOn
    ? { nodes: allNodes.filter(n => neighbours.has(n.id)), edges: allEdges.filter(e => neighbours.has(e.from) && neighbours.has(e.to)) }
    : { nodes: allNodes, edges: allEdges }, [allNodes, allEdges, focusOn, neighbours]);
  const deg = useMemo(() => degrees(nodes, edges), [nodes, edges]);
  const layoutHeight = typeof height === "number" ? height : 640;
  const positions = useMemo(() => layoutNodes(nodes, edges, chosen.layout, chosen.direction, layoutHeight), [nodes, edges, chosen.layout, chosen.direction, layoutHeight]);
  const nameCut = useMemo(() => { const rs = nodes.map(n => radiusFor(n, deg[n.id] ?? 0)).sort((a, b) => b - a); return nodes.length > 100 ? Math.max(26, rs[Math.floor(rs.length * 0.15)] ?? 0) : nodes.length > 40 ? (rs[Math.floor(rs.length * 0.4)] ?? 0) : 0; }, [nodes, deg]);   // busy maps: names only on the hubs
  const showAllLabels = edges.length <= 60;
  const wanted = useMemo<Node<BubbleData>[]>(() => nodes.map(n => { const r = radiusFor(n, deg[n.id] ?? 0); const p = positions[n.id] ?? { x: 0, y: 0 }; const inSpot = spotId === undefined || neighbours.has(n.id);
    return { id: n.id, type: "bubble", position: { x: p.x - r, y: p.y - r }, data: { node: n, r, dim: !inSpot, showName: inSpot && (r >= nameCut || n.selected === true), onSelect, onExpand }, draggable: true, selectable: false }; }), [nodes, positions, onSelect, onExpand, deg, spotId, neighbours, nameCut]);
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<Node<BubbleData>>(wanted);
  useEffect(() => { setRfNodes(prev => { const m = new Map(prev.map(n => [n.id, n])); return wanted.map(n => ({ ...n, measured: m.get(n.id)?.measured })); }); }, [wanted, setRfNodes]);
  const ids = useMemo(() => new Set(nodes.map(n => n.id)), [nodes]);
  const wantedEdges = useMemo<Edge[]>(() => edges.filter(e => ids.has(e.from) && ids.has(e.to)).map((e, i) => {
    const hot = selectedId !== undefined && (e.from === selectedId || e.to === selectedId);
    const dimmed = spotId !== undefined && !hot;
    const color = e.color ?? "#A5ABB6";
    return { id: `e${i}-${e.from}-${e.to}`, source: e.from, target: e.to, type: "floating", label: showAllLabels || hot ? e.label : undefined,
      markerEnd: { type: MarkerType.ArrowClosed, color, width: 14, height: 14 },
      style: { stroke: color, strokeWidth: hot ? Math.max(2, e.width ?? 1.5) : e.width ?? 1.5, strokeDasharray: e.dashed ? "5 4" : undefined, opacity: dimmed ? 0.3 : 1 },
      labelStyle: { fontSize: 10.5, fontWeight: 600, fill: e.labelColor ?? "#5F5F60" }, labelBgStyle: { fill: "#fff" } };
  }), [edges, ids, selectedId, spotId, showAllLabels]);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState<Edge>(wantedEdges);
  useEffect(() => { setRfEdges(wantedEdges); }, [wantedEdges, setRfEdges]);
  const relayout = useCallback(() => setStep(s => s + 1), []);
  useEffect(() => { const t = setTimeout(() => flow.fitView({ padding: 0.1, duration: 200, maxZoom: 1.4 }), 30); return () => clearTimeout(t); }, [flow, nodes.length, chosen.layout, chosen.direction, focusOn, hidden]);
  const focus = chosen.layout === "given" || allNodes.length <= 1 ? undefined : { on: focusOn, toggle: () => setFocused(f => !f) };
  const selectedLabel = allNodes.find(n => n.id === selectedId)?.label ?? "";
  const counts = `${nodes.length} node${nodes.length === 1 ? "" : "s"} · ${edges.length} edge${edges.length === 1 ? "" : "s"}`;
  const shown = focusOn ? `${counts} · ${selectedLabel} and its neighbours (${allNodes.length} in all)` : focused && selectedId !== undefined && !hasNeighbours ? `${counts} · ${selectedLabel} has no relationships` : counts;

  return (
    <div className={`stage ${dotted ? "dotted" : ""}`} style={{ height }}>
      {children && <div className="stage-backdrop" aria-hidden="true">{children}</div>}
      <ReactFlow nodes={rfNodes} edges={rfEdges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} nodeTypes={NODE_TYPES} edgeTypes={EDGE_TYPES} fitView fitViewOptions={{ padding: 0.1 }} minZoom={0.05} maxZoom={3} nodesConnectable={false} elementsSelectable={false}
        proOptions={{ hideAttribution: true }} onNodeClick={(_, n) => onSelect?.(n.id)} onNodeDoubleClick={(_, n) => onExpand?.(n.id)} nodeOrigin={[0, 0]} deleteKeyCode={null} zoomOnDoubleClick={false}>
        {dotted && <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#E8E8EA" />}
        {nodes.length > 15 && <MiniMap pannable zoomable nodeColor={n => (n.data as BubbleData).node.fill} maskColor="rgba(244,244,245,.7)" style={{ height: 90, width: 140 }} />}
      </ReactFlow>
      <Tools extra={tools} onRelayout={fixedLayout === "given" ? undefined : relayout} layoutName={chosen.name} focus={focus} nodes={allNodes} onFind={onSelect} />
      {(groups?.length || legend) && <div className="stage-legend">
        {groups?.map(g => <label key={g.id} className="row" style={{ gap: 5, cursor: "pointer" }}><input type="checkbox" checked={!hidden.has(g.id)} onChange={e => setHidden(h => { const n = new Set(h); if (e.target.checked) n.delete(g.id); else n.add(g.id); return n; })} aria-label={`Show ${g.label}`} /><i style={{ width: 9, height: 9, borderRadius: "50%", background: g.color, display: "inline-block" }} />{g.label}</label>)}
        {legend}
      </div>}
      {(shown || status) && <div className="stage-status">{status ? <>{status} · {shown}</> : shown}</div>}
    </div>
  );
}

export interface StageProps { nodes: StageNode[]; edges: StageEdge[]; height: number | string; dotted?: boolean; onSelect?: (id: string) => void; onExpand?: (id: string) => void; legend?: ReactNode; groups?: StageGroup[]; tools?: ReactNode; status?: ReactNode; children?: ReactNode; layout?: StageLayout; spotlight?: boolean }

export function Stage(props: StageProps) {
  return <ReactFlowProvider><StageInner {...props} /></ReactFlowProvider>;
}

export const glyphOf = (id: string) => (id === "KeyAccount" ? "KA" : id[0] ?? "?");
