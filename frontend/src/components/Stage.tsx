// The node-link stage: React Flow for pan, zoom, fit and edge routing, dagre for automatic
// layout. Screens keep describing nodes and edges in their own terms; positions are computed
// here unless a screen asks for its own (`layout="given"`, as Explore does for its star).
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Background, BackgroundVariant, Handle, MiniMap, Position, ReactFlow, ReactFlowProvider, useEdgesState, useNodesState, useReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import dagre from "@dagrejs/dagre";

export interface StageNode { id: string; label: string; glyph: string; x: number; y: number; fill: string; border?: string; selected?: boolean; props?: number; title?: string; size?: "md" | "sm" | "lg" }
export interface StageEdge { from: string; to: string; label: string; color?: string; dashed?: boolean; width?: number; labelColor?: string }
export type StageLayout = "dagre" | "given";
type Direction = "TB" | "LR";

const HEIGHT = { sm: 28, md: 34, lg: 36 } as const;
const GIVEN_WIDTH = 1100;   // virtual canvas for percentage positions

function pillWidth(n: StageNode): number {
  const font = n.size === "lg" ? 7.9 : n.size === "sm" ? 6.9 : 7.5;
  return Math.round(28 + (n.size === "lg" ? 26 : n.size === "sm" ? 20 : 24) + n.label.length * font + (n.props !== undefined ? 26 : 0));
}

/** Positions from dagre (hierarchical, deterministic) or from the nodes' own percentages.
 *  Nodes without any edge are packed into a grid under the connected part instead of being
 *  strung out along one dagre rank, which is what made large ontologies unreadable. */
export function layoutNodes(nodes: StageNode[], edges: StageEdge[], layout: StageLayout, direction: Direction, height: number): Record<string, { x: number; y: number }> {
  if (layout === "given") return Object.fromEntries(nodes.map(n => [n.id, { x: (n.x / 100) * GIVEN_WIDTH - pillWidth(n) / 2, y: (n.y / 100) * Math.max(height, 400) - HEIGHT[n.size ?? "md"] / 2 }]));
  const ids = new Set(nodes.map(n => n.id));
  const linked = new Set(edges.filter(e => ids.has(e.from) && ids.has(e.to) && e.from !== e.to).flatMap(e => [e.from, e.to]));
  const connected = nodes.filter(n => linked.has(n.id)), isolated = nodes.filter(n => !linked.has(n.id));
  const out: Record<string, { x: number; y: number }> = {};
  let width = 0, bottom = 0;
  if (connected.length) {
    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: direction, nodesep: 24, ranksep: direction === "TB" ? 56 : 80, marginx: 8, marginy: 8, ranker: "tight-tree" });
    g.setDefaultEdgeLabel(() => ({}));
    for (const n of connected) g.setNode(n.id, { width: pillWidth(n), height: HEIGHT[n.size ?? "md"] });
    for (const e of edges) if (linked.has(e.from) && linked.has(e.to) && e.from !== e.to) g.setEdge(e.from, e.to);
    dagre.layout(g);
    for (const n of connected) { const p = g.node(n.id); out[n.id] = { x: p.x - pillWidth(n) / 2, y: p.y - HEIGHT[n.size ?? "md"] / 2 }; width = Math.max(width, p.x + pillWidth(n) / 2); bottom = Math.max(bottom, p.y + HEIGHT[n.size ?? "md"] / 2); }
  }
  if (isolated.length) {   // a grid as wide as the connected part (at least 700px), row by row
    const maxW = Math.max(width, 700); let x = 0, y = bottom + (connected.length ? 72 : 0), rowH = 0;
    for (const n of isolated) {
      const w = pillWidth(n), h = HEIGHT[n.size ?? "md"];
      if (x > 0 && x + w > maxW) { x = 0; y += rowH + 18; rowH = 0; }
      out[n.id] = { x, y }; x += w + 18; rowH = Math.max(rowH, h);
    }
  }
  return out;
}

type PillData = { node: StageNode; onSelect?: (id: string) => void; attach: "TB" | "LR" | "center" };

function Pill({ data }: NodeProps<Node<PillData>>) {
  const { node: n, onSelect, attach } = data;
  const h = HEIGHT[n.size ?? "md"]; const g = n.size === "lg" ? 26 : n.size === "sm" ? 20 : 24;
  // Edges attach where the layout flows: top/bottom for ranks, left/right for LR, the centre for a star.
  const [tIn, tOut] = attach === "LR" ? [Position.Left, Position.Right] : [Position.Top, Position.Bottom];
  const centred = attach === "center" ? { top: "50%", left: "50%", transform: "translate(-50%, -50%)" } : undefined;
  return (
    <>
      <Handle type="target" position={tIn} className="stage-handle" style={centred} />
      <button type="button" className={`node ${n.selected ? "selected" : ""}`} title={n.title} aria-pressed={n.selected} onClick={() => onSelect?.(n.id)}
        style={{ height: h, fontSize: n.size === "lg" ? 13 : n.size === "sm" ? 11.5 : 12.5, borderColor: n.selected ? "#2249FF" : n.border }}>
        <span className="glyph" style={{ width: g, height: g, background: n.fill, fontSize: n.size === "sm" ? 9 : 11 }}>{n.glyph}</span>{n.label}{n.props !== undefined && <span className="props">{n.props}</span>}
      </button>
      <Handle type="source" position={tOut} className="stage-handle" style={centred} />
    </>
  );
}
const NODE_TYPES = { pill: Pill };

function Tools({ extra, onRelayout, focus }: { extra?: ReactNode; onRelayout?: () => void; focus?: { on: boolean; toggle: () => void } }) {
  const flow = useReactFlow();
  return (
    <div className="stage-tools">
      {focus && <button type="button" className={focus.on ? "active" : ""} title={focus.on ? "Show every class" : "Show only the selected class and its neighbours"} aria-label={focus.on ? "Show all" : "Focus on selection"} aria-pressed={focus.on} onClick={focus.toggle}>◎</button>}
      <button type="button" title="Zoom in" aria-label="Zoom in" onClick={() => flow.zoomIn()}>+</button>
      <button type="button" title="Zoom out" aria-label="Zoom out" onClick={() => flow.zoomOut()}>−</button>
      <button type="button" title="Fit" aria-label="Fit" onClick={() => flow.fitView({ padding: 0.15, duration: 300 })}>⤢</button>
      {onRelayout && <button type="button" title="Switch layout direction" aria-label="Switch layout direction" onClick={onRelayout}>↻</button>}
      {extra}
    </div>
  );
}

const FOCUS_ABOVE = 30;   // graphs bigger than this open on the selected node's neighbourhood

function StageInner({ nodes: allNodes, edges: allEdges, height, dotted, onSelect, legend, tools, status, children, layout }: StageProps) {
  const [direction, setDirection] = useState<Direction>(allNodes.length > 24 ? "LR" : "TB");
  const [focused, setFocused] = useState(allNodes.length > FOCUS_ABOVE);
  const flow = useReactFlow();
  const selectedId = allNodes.find(n => n.selected)?.id;
  const focusOn = focused && layout !== "given" && selectedId !== undefined && allNodes.length > 1;
  const { nodes, edges } = useMemo(() => {
    if (!focusOn) return { nodes: allNodes, edges: allEdges };
    const keep = new Set([selectedId!, ...allEdges.filter(e => e.from === selectedId || e.to === selectedId).flatMap(e => [e.from, e.to])]);
    return { nodes: allNodes.filter(n => keep.has(n.id)), edges: allEdges.filter(e => keep.has(e.from) && keep.has(e.to)) };
  }, [allNodes, allEdges, focusOn, selectedId]);
  const positions = useMemo(() => layoutNodes(nodes, edges, layout ?? "dagre", direction, height), [nodes, edges, layout, direction, height]);
  const showAllLabels = edges.length <= 40;
  const attach: PillData["attach"] = layout === "given" ? "center" : direction;
  const wanted = useMemo<Node<PillData>[]>(() => nodes.map(n => ({ id: n.id, type: "pill", position: positions[n.id] ?? { x: 0, y: 0 }, data: { node: n, onSelect, attach }, draggable: true, selectable: false })), [nodes, positions, onSelect, attach]);
  // React Flow reports each node's measured size through onNodesChange; keeping the nodes in its own
  // state hook is what turns them visible. Recomputed nodes replace the state but keep measurements.
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<Node<PillData>>(wanted);
  useEffect(() => { setRfNodes(prev => { const m = new Map(prev.map(n => [n.id, n])); return wanted.map(n => ({ ...n, measured: m.get(n.id)?.measured })); }); }, [wanted, setRfNodes]);
  const ids = useMemo(() => new Set(nodes.map(n => n.id)), [nodes]);
  const wantedEdges = useMemo<Edge[]>(() => edges.filter(e => ids.has(e.from) && ids.has(e.to)).map((e, i) => {
    const hot = selectedId !== undefined && (e.from === selectedId || e.to === selectedId);
    return { id: `e${i}-${e.from}-${e.to}`, source: e.from, target: e.to, type: layout === "given" ? "straight" : "default", label: showAllLabels || hot ? e.label : undefined,
      style: { stroke: e.color ?? "#B9C4FF", strokeWidth: hot ? Math.max(2, e.width ?? 1.5) : e.width ?? 1.5, strokeDasharray: e.dashed ? "5 4" : undefined, opacity: selectedId && !hot ? 0.45 : 1 },
      labelStyle: { fontSize: 10.5, fontWeight: 600, fill: e.labelColor ?? "#7A7A80" }, labelBgStyle: { fill: "#fff", fillOpacity: 0.95 }, labelBgPadding: [5, 2] as [number, number], labelBgBorderRadius: 4, zIndex: hot ? 1 : 0 };
  }), [edges, ids, selectedId, showAllLabels, layout]);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState<Edge>(wantedEdges);
  useEffect(() => { setRfEdges(wantedEdges); }, [wantedEdges, setRfEdges]);
  const relayout = useCallback(() => setDirection(d => (d === "TB" ? "LR" : "TB")), []);
  useEffect(() => { const t = setTimeout(() => flow.fitView({ padding: 0.15, duration: 200, maxZoom: 1.25 }), 30); return () => clearTimeout(t); }, [flow, nodes.length, direction, layout, selectedId, focusOn]);
  const focus = layout === "given" || allNodes.length <= 1 ? undefined : { on: focusOn, toggle: () => setFocused(f => !f) };
  const shown = focusOn ? `${nodes.length} of ${allNodes.length} shown · ${allNodes.find(n => n.id === selectedId)?.label ?? ""} and its neighbours` : null;

  return (
    <div className={`stage ${dotted ? "dotted" : ""}`} style={{ height }}>
      {children && <div className="stage-backdrop" aria-hidden="true">{children}</div>}
      <ReactFlow nodes={rfNodes} edges={rfEdges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} nodeTypes={NODE_TYPES} fitView fitViewOptions={{ padding: 0.15 }} minZoom={0.15} maxZoom={2.5} nodesConnectable={false} elementsSelectable={false}
        proOptions={{ hideAttribution: true }} onNodeClick={(_, n) => onSelect?.(n.id)} nodeOrigin={[0, 0]} deleteKeyCode={null}>
        {dotted && <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#E8E8EA" />}
        {nodes.length > 15 && <MiniMap pannable zoomable nodeColor={n => (n.data as PillData).node.fill} maskColor="rgba(244,244,245,.7)" style={{ height: 90, width: 140 }} />}
      </ReactFlow>
      <Tools extra={tools} onRelayout={layout === "given" ? undefined : relayout} focus={focus} />
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
