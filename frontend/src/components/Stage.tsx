// The node-link stage, drawn the way graph browsers draw graphs: coloured bubbles with the name
// inside, arrows carrying the relationship name, a force-directed layout, drag, pan and zoom.
// React Flow is the canvas, d3-force places the nodes (dagre is the alternative ranked layout),
// and every screen keeps describing nodes and edges in its own terms.
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Background, BackgroundVariant, BaseEdge, EdgeLabelRenderer, Handle, MarkerType, MiniMap, Position, ReactFlow, ReactFlowProvider, getStraightPath, useEdgesState, useInternalNode, useNodesState, useReactFlow, type Edge, type EdgeProps, type Node, type NodeProps } from "@xyflow/react";
import dagre from "@dagrejs/dagre";
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY } from "d3-force";

export interface StageNode { id: string; label: string; glyph: string; x: number; y: number; fill: string; border?: string; selected?: boolean; props?: number; title?: string; size?: "md" | "sm" | "lg"; pin?: boolean }
export interface StageEdge { from: string; to: string; label: string; color?: string; dashed?: boolean; width?: number; labelColor?: string }
export type StageLayout = "force" | "dagre" | "given";
type Direction = "TB" | "LR";

const RADIUS = { sm: 22, md: 30, lg: 38 } as const;
const GIVEN_WIDTH = 1100;   // virtual canvas for percentage positions

/** A stable colour per class name, the way graph browsers colour labels. */
const PALETTE = ["#4C8EDA", "#57C7E3", "#F16667", "#8DCC93", "#ECB5C9", "#FFC454", "#DA7194", "#569480", "#C990C0", "#F79767", "#A5ABB6", "#D9C8AE"];
export function colorFor(name: string): string {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

const radius = (n: StageNode) => RADIUS[n.size ?? "md"];

/** Node centres. Force: a settled d3 simulation, deterministic for the same input. */
export function layoutNodes(nodes: StageNode[], edges: StageEdge[], layout: StageLayout, direction: Direction, height: number): Record<string, { x: number; y: number }> {
  if (layout === "given") return Object.fromEntries(nodes.map(n => [n.id, { x: (n.x / 100) * GIVEN_WIDTH, y: (n.y / 100) * Math.max(height, 400) }]));
  const ids = new Set(nodes.map(n => n.id));
  const links = edges.filter(e => ids.has(e.from) && ids.has(e.to) && e.from !== e.to);
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
      .distance(l => 70 + (byId.get(typeof l.source === "string" ? l.source : (l.source as Sim).id)?.r ?? 30) + (byId.get(typeof l.target === "string" ? l.target : (l.target as Sim).id)?.r ?? 30)).strength(0.5))
    .force("charge", forceManyBody().strength(-420))
    .force("collide", forceCollide<Sim>().radius(d => d.r + 14).strength(0.9))
    .force("x", forceX(0).strength(0.04)).force("y", forceY(0).strength(0.04))
    .force("center", forceCenter(0, 0))
    .stop();
  for (let i = 0; i < 300; i++) simulation.tick();
  return Object.fromEntries(sim.map(s => [s.id, { x: s.x, y: s.y }]));
}

type BubbleData = { node: StageNode; onSelect?: (id: string) => void };

function Bubble({ data }: NodeProps<Node<BubbleData>>) {
  const { node: n, onSelect } = data;
  const r = radius(n);
  const max = n.size === "lg" ? 14 : n.size === "sm" ? 9 : 12;
  const short = n.label.length > max ? n.label.slice(0, max - 1) + "…" : n.label;
  return (
    <>
      <Handle type="target" position={Position.Top} className="stage-handle" />
      <button type="button" className={`bubble ${n.selected ? "selected" : ""}`} title={n.title ? `${n.label} · ${n.title}` : n.label} aria-label={n.label} aria-pressed={n.selected} onClick={() => onSelect?.(n.id)}
        style={{ width: r * 2, height: r * 2, background: n.fill, borderColor: n.border ?? "rgba(0,0,0,.12)", fontSize: n.size === "lg" ? 12.5 : n.size === "sm" ? 9.5 : 11 }}>
        <span className="cap">{short}</span>
        {n.props !== undefined && <span className="props" aria-hidden="true">{n.props}</span>}
        {short !== n.label && <span className="name" aria-hidden="true">{n.label}</span>}
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
      {label && <EdgeLabelRenderer><div className="stage-edge-label" style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)`, color: fill, background: bg }}>{label}</div></EdgeLabelRenderer>}
    </>
  );
}
const EDGE_TYPES = { floating: FloatingEdge };

function Tools({ extra, onRelayout, layoutName, focus }: { extra?: ReactNode; onRelayout?: () => void; layoutName: string; focus?: { on: boolean; toggle: () => void } }) {
  const flow = useReactFlow();
  return (
    <div className="stage-tools">
      {focus && <button type="button" className={focus.on ? "active" : ""} title={focus.on ? "Show every class" : "Show only the selected class and its neighbours"} aria-label={focus.on ? "Show all" : "Focus on selection"} aria-pressed={focus.on} onClick={focus.toggle}>◎</button>}
      <button type="button" title="Zoom in" aria-label="Zoom in" onClick={() => flow.zoomIn()}>+</button>
      <button type="button" title="Zoom out" aria-label="Zoom out" onClick={() => flow.zoomOut()}>−</button>
      <button type="button" title="Fit" aria-label="Fit" onClick={() => flow.fitView({ padding: 0.15, duration: 300 })}>⤢</button>
      {onRelayout && <button type="button" title={`Layout: ${layoutName} · click to change`} aria-label="Switch layout" onClick={onRelayout}>↻</button>}
      {extra}
    </div>
  );
}

const FOCUS_ABOVE = 30;   // graphs bigger than this open on the selected node's neighbourhood
const LAYOUTS: { layout: StageLayout; direction: Direction; name: string }[] = [{ layout: "force", direction: "TB", name: "force" }, { layout: "dagre", direction: "TB", name: "ranked, top to bottom" }, { layout: "dagre", direction: "LR", name: "ranked, left to right" }];

function StageInner({ nodes: allNodes, edges: allEdges, height, dotted, onSelect, legend, tools, status, children, layout: fixedLayout }: StageProps) {
  const [step, setStep] = useState(0);
  const chosen = fixedLayout === "given" ? { layout: "given" as const, direction: "TB" as const, name: "given" } : LAYOUTS[step % LAYOUTS.length];
  const [focused, setFocused] = useState(allNodes.length > FOCUS_ABOVE);
  const flow = useReactFlow();
  const selectedId = allNodes.find(n => n.selected)?.id;
  const hasNeighbours = selectedId !== undefined && allEdges.some(e => e.from === selectedId || e.to === selectedId);
  const focusOn = focused && chosen.layout !== "given" && selectedId !== undefined && allNodes.length > 1 && hasNeighbours;
  const { nodes, edges } = useMemo(() => {
    if (!focusOn) return { nodes: allNodes, edges: allEdges };
    const keep = new Set([selectedId!, ...allEdges.filter(e => e.from === selectedId || e.to === selectedId).flatMap(e => [e.from, e.to])]);
    return { nodes: allNodes.filter(n => keep.has(n.id)), edges: allEdges.filter(e => keep.has(e.from) && keep.has(e.to)) };
  }, [allNodes, allEdges, focusOn, selectedId]);
  const positions = useMemo(() => layoutNodes(nodes, edges, chosen.layout, chosen.direction, height), [nodes, edges, chosen.layout, chosen.direction, height]);
  const showAllLabels = edges.length <= 60;
  const wanted = useMemo<Node<BubbleData>[]>(() => nodes.map(n => { const r = radius(n); const p = positions[n.id] ?? { x: 0, y: 0 }; return { id: n.id, type: "bubble", position: { x: p.x - r, y: p.y - r }, data: { node: n, onSelect }, draggable: true, selectable: false }; }), [nodes, positions, onSelect]);
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<Node<BubbleData>>(wanted);
  useEffect(() => { setRfNodes(prev => { const m = new Map(prev.map(n => [n.id, n])); return wanted.map(n => ({ ...n, measured: m.get(n.id)?.measured })); }); }, [wanted, setRfNodes]);
  const ids = useMemo(() => new Set(nodes.map(n => n.id)), [nodes]);
  const wantedEdges = useMemo<Edge[]>(() => edges.filter(e => ids.has(e.from) && ids.has(e.to)).map((e, i) => {
    const hot = selectedId !== undefined && (e.from === selectedId || e.to === selectedId);
    const color = e.color ?? "#A5ABB6";
    return { id: `e${i}-${e.from}-${e.to}`, source: e.from, target: e.to, type: "floating", label: showAllLabels || hot ? e.label : undefined,
      markerEnd: { type: MarkerType.ArrowClosed, color, width: 14, height: 14 },
      style: { stroke: color, strokeWidth: hot ? Math.max(2, e.width ?? 1.5) : e.width ?? 1.5, strokeDasharray: e.dashed ? "5 4" : undefined, opacity: selectedId && !hot ? 0.4 : 1 },
      labelStyle: { fontSize: 10.5, fontWeight: 600, fill: e.labelColor ?? "#5F5F60" }, labelBgStyle: { fill: "#fff" } };
  }), [edges, ids, selectedId, showAllLabels]);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState<Edge>(wantedEdges);
  useEffect(() => { setRfEdges(wantedEdges); }, [wantedEdges, setRfEdges]);
  const relayout = useCallback(() => setStep(s => s + 1), []);
  useEffect(() => { const t = setTimeout(() => flow.fitView({ padding: 0.12, duration: 200, maxZoom: 1.4 }), 30); return () => clearTimeout(t); }, [flow, nodes.length, chosen.layout, chosen.direction, selectedId, focusOn]);
  const focus = chosen.layout === "given" || allNodes.length <= 1 ? undefined : { on: focusOn, toggle: () => setFocused(f => !f) };
  const selectedLabel = allNodes.find(n => n.id === selectedId)?.label ?? "";
  const shown = focusOn ? `${nodes.length} of ${allNodes.length} shown · ${selectedLabel} and its neighbours` : focused && selectedId !== undefined && !hasNeighbours && allNodes.length > FOCUS_ABOVE ? `${selectedLabel} has no relationships · showing all ${allNodes.length}` : null;

  return (
    <div className={`stage ${dotted ? "dotted" : ""}`} style={{ height }}>
      {children && <div className="stage-backdrop" aria-hidden="true">{children}</div>}
      <ReactFlow nodes={rfNodes} edges={rfEdges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} nodeTypes={NODE_TYPES} edgeTypes={EDGE_TYPES} fitView fitViewOptions={{ padding: 0.12 }} minZoom={0.1} maxZoom={3} nodesConnectable={false} elementsSelectable={false}
        proOptions={{ hideAttribution: true }} onNodeClick={(_, n) => onSelect?.(n.id)} nodeOrigin={[0, 0]} deleteKeyCode={null}>
        {dotted && <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#E8E8EA" />}
        {nodes.length > 15 && <MiniMap pannable zoomable nodeColor={n => (n.data as BubbleData).node.fill} maskColor="rgba(244,244,245,.7)" style={{ height: 90, width: 140 }} />}
      </ReactFlow>
      <Tools extra={tools} onRelayout={fixedLayout === "given" ? undefined : relayout} layoutName={chosen.name} focus={focus} />
      {legend && <div className="stage-legend">{legend}</div>}
      {(shown || status) && <div className="stage-status">{shown ?? status}</div>}
    </div>
  );
}

export interface StageProps { nodes: StageNode[]; edges: StageEdge[]; height: number; dotted?: boolean; onSelect?: (id: string) => void; legend?: ReactNode; tools?: ReactNode; status?: ReactNode; children?: ReactNode; layout?: StageLayout }

export function Stage(props: StageProps) {
  return <ReactFlowProvider><StageInner {...props} /></ReactFlowProvider>;
}

export const glyphOf = (id: string) => (id === "KeyAccount" ? "KA" : id[0] ?? "?");
