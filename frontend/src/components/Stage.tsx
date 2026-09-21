import type { ReactNode } from "react";

// A node-link stage drawn with absolutely positioned pills over an SVG wire layer,
// as in the design. Positions are percentages so the stage scales with its container.
export interface StageNode { id: string; label: string; glyph: string; x: number; y: number; fill: string; border?: string; selected?: boolean; props?: number; title?: string; size?: "md" | "sm" | "lg" }
export interface StageEdge { from: string; to: string; label: string; color?: string; dashed?: boolean; width?: number; labelColor?: string }

export function Stage({ nodes, edges, height, dotted, onSelect, legend, tools, status, children }: { nodes: StageNode[]; edges: StageEdge[]; height: number; dotted?: boolean; onSelect?: (id: string) => void; legend?: ReactNode; tools?: ReactNode; status?: ReactNode; children?: ReactNode }) {
  const pos = Object.fromEntries(nodes.map(n => [n.id, n]));
  const lines = edges.filter(e => pos[e.from] && pos[e.to]).map(e => ({ ...e, a: pos[e.from], b: pos[e.to] }));
  return (
    <div className={`stage ${dotted ? "dotted" : ""}`} style={{ height }}>
      <svg className="wires" aria-hidden="true">
        {lines.map((e, i) => <line key={i} x1={`${e.a.x}%`} y1={`${e.a.y}%`} x2={`${e.b.x}%`} y2={`${e.b.y}%`} style={{ stroke: e.color ?? "#B9C4FF", strokeWidth: e.width ?? 1.5, strokeDasharray: e.dashed ? "5 4" : "none" }} />)}
      </svg>
      {children}
      {lines.map((e, i) => e.label ? <span key={`l${i}`} className="edge-label" style={{ left: `${(e.a.x + e.b.x) / 2}%`, top: `${(e.a.y + e.b.y) / 2}%`, color: e.labelColor }}>{e.label}</span> : null)}
      {nodes.map(n => {
        const h = n.size === "lg" ? 36 : n.size === "sm" ? 28 : 34; const g = n.size === "lg" ? 26 : n.size === "sm" ? 20 : 24;
        return (
          <button key={n.id} type="button" className={`node ${n.selected ? "selected" : ""}`} title={n.title} aria-pressed={n.selected} onClick={() => onSelect?.(n.id)}
            style={{ left: `${n.x}%`, top: `${n.y}%`, height: h, fontSize: n.size === "lg" ? 13 : n.size === "sm" ? 11.5 : 12.5, borderColor: n.selected ? "#2249FF" : n.border, boxShadow: n.selected ? `0 0 0 ${n.size === "lg" ? 6 : 4}px #EEF1FF` : undefined }}>
            <span className="glyph" style={{ width: g, height: g, background: n.fill, fontSize: n.size === "sm" ? 9 : 11 }}>{n.glyph}</span>{n.label}{n.props !== undefined && <span className="props">{n.props}</span>}
          </button>
        );
      })}
      {tools && <div className="stage-tools">{tools}</div>}
      {legend && <div className="stage-legend">{legend}</div>}
      {status && <div className="stage-status">{status}</div>}
    </div>
  );
}

export const STAGE_TOOLS = [["+", "Zoom in"], ["−", "Zoom out"], ["⤢", "Fit (F)"], ["↻", "Layout"]] as const;
export function StageTools({ onAction }: { onAction?: (title: string) => void }) {
  return <>{STAGE_TOOLS.map(([g, t]) => <button key={t} type="button" title={t} aria-label={t} onClick={() => onAction?.(t)}>{g}</button>)}</>;
}

export const glyphOf = (id: string) => (id === "KeyAccount" ? "KA" : id[0] ?? "?");
