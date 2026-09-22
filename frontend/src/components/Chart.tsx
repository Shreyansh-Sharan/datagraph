// A chart the assistant describes in a ```chart block: bars for peers, a line for time. Plain SVG,
// one to three series, compact value labels, readable by assistive technology through its title.
export interface ChartSpec { type?: "bar" | "line"; title?: string; unit?: string; series: { name?: string; points: { x: string | number; y: number | null }[] }[] }

const COLORS = ["var(--blue)", "#f2994a", "#27ae60"];
export const compact = (v: number): string => {
  const a = Math.abs(v);
  const f = (n: number, s: string) => `${n.toLocaleString("en-US", { maximumFractionDigits: Math.abs(n) >= 100 ? 0 : 1 })}${s}`;
  if (a >= 1e9) return f(v / 1e9, "B");
  if (a >= 1e6) return f(v / 1e6, "M");
  if (a >= 1e3) return f(v / 1e3, "k");
  return v.toLocaleString("en-US", { maximumFractionDigits: Number.isInteger(v) ? 0 : 2 });
};

export function parseChart(text: string): ChartSpec | null {
  try {
    const raw = JSON.parse(text);
    const series = Array.isArray(raw?.series) ? raw.series : Array.isArray(raw?.points) ? [{ name: raw.name, points: raw.points }] : Array.isArray(raw?.data) ? [{ points: raw.data }] : null;
    if (!series) return null;
    const clean = series.map((s: { name?: string; points?: unknown[] }) => ({
      name: s.name, points: (s.points ?? []).map((p: unknown) => {
        const q = p as { x?: unknown; label?: unknown; y?: unknown; value?: unknown };
        const y = Number(q.y ?? q.value); return { x: String(q.x ?? q.label ?? ""), y: Number.isFinite(y) ? y : null };
      }),
    })).filter((s: { points: unknown[] }) => s.points.length);
    return clean.length ? { type: raw.type === "line" ? "line" : "bar", title: raw.title, unit: raw.unit, series: clean.slice(0, 3) } : null;
  } catch { return null; }
}

export function Chart({ spec }: { spec: ChartSpec }) {
  const W = 560, H = 240, L = 52, R = 12, T = 14, B = 34;
  const xs = Array.from(new Set(spec.series.flatMap(s => s.points.map(p => String(p.x)))));
  const ys = spec.series.flatMap(s => s.points.map(p => p.y)).filter((y): y is number => y != null);
  const max = Math.max(0, ...ys), min = Math.min(0, ...ys);
  const span = max - min || 1;
  const y = (v: number) => T + (H - T - B) * (1 - (v - min) / span);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map(f => min + span * f);
  const slot = (W - L - R) / Math.max(1, xs.length);
  const line = spec.type === "line";
  const bw = Math.max(4, (slot * 0.7) / spec.series.length);
  const label = spec.title ?? "Chart";
  return (
    <figure className="chart" role="img" aria-label={label}>
      {spec.title && <figcaption>{spec.title}{spec.unit ? <span className="muted-2"> · {spec.unit}</span> : null}</figcaption>}
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" aria-hidden="true">
        {ticks.map(t => <g key={t}><line x1={L} x2={W - R} y1={y(t)} y2={y(t)} className="grid" /><text x={L - 6} y={y(t) + 4} textAnchor="end" className="tick">{compact(t)}</text></g>)}
        {xs.map((x, i) => <text key={x} x={L + slot * (i + 0.5)} y={H - B + 16} textAnchor="middle" className="tick">{x}</text>)}
        {spec.series.map((s, si) => {
          const at = (x: string) => s.points.find(p => String(p.x) === x)?.y ?? null;
          if (line) {
            const pts = xs.map((x, i) => [L + slot * (i + 0.5), at(x)] as const).filter((p): p is readonly [number, number] => p[1] != null);
            return <g key={si} style={{ color: COLORS[si] }}>
              <polyline points={pts.map(([px, v]) => `${px},${y(v)}`).join(" ")} fill="none" stroke="currentColor" strokeWidth={2} />
              {pts.map(([px, v]) => <circle key={px} cx={px} cy={y(v)} r={3.5} fill="currentColor"><title>{`${s.name ?? ""} ${compact(v)}`}</title></circle>)}
            </g>;
          }
          return <g key={si} style={{ color: COLORS[si] }}>
            {xs.map((x, i) => { const v = at(x); if (v == null) return null; const px = L + slot * i + (slot - bw * spec.series.length) / 2 + bw * si;
              return <rect key={x} x={px} y={Math.min(y(v), y(0))} width={bw - 1} height={Math.max(1, Math.abs(y(v) - y(0)))} fill="currentColor" rx={2}><title>{`${x}${s.name ? ` · ${s.name}` : ""}: ${compact(v)}`}</title></rect>; })}
          </g>;
        })}
      </svg>
      {spec.series.length > 1 && <ul className="chart-legend">{spec.series.map((s, i) => <li key={i}><i style={{ background: COLORS[i] }} />{s.name ?? `Series ${i + 1}`}</li>)}</ul>}
    </figure>
  );
}
