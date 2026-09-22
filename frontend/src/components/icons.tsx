// 16px stroke icons from the design. `name` picks a path; unknown names fall back to "overview".
export const ICON: Record<string, string> = {
  overview: "M2 2h5v5H2zM9 2h5v5H9zM2 9h5v5H2zM9 9h5v5H9z",
  settings: "M8 5.5a2.5 2.5 0 1 0 0 5a2.5 2.5 0 1 0 0-5M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4",
  metadata: "M2 3h12v10H2zM2 7h12M6 3v10",
  ontology: "M8 2.5a1.5 1.5 0 1 0 0 3a1.5 1.5 0 1 0 0-3M3 10.5a1.5 1.5 0 1 0 0 3a1.5 1.5 0 1 0 0-3M13 10.5a1.5 1.5 0 1 0 0 3a1.5 1.5 0 1 0 0-3M7 5.2L4 10.3M9 5.2l3 5.1",
  mapping: "M2 4h4v3H2zM2 9h4v3H2zM10 6.5h4v3h-4zM6 5.5h2v3h2M6 10.5h2v-2h2",
  rules: "M3 2h10v12H3zM5.5 5.5h5M5.5 8h5M5.5 10.5h3",
  quality: "M8 1.5l5 2v4c0 3-2.2 5.3-5 6.5C5.2 12.8 3 10.5 3 7.5v-4zM5.8 8l1.6 1.6L10.5 6.4",
  build: "M2 12l4-4M9.5 2.5a3 3 0 0 0 3.8 3.8L14 7.5a4.5 4.5 0 1 1-6.3-6.3z",
  explore: "M7 2.5a4.5 4.5 0 1 0 0 9a4.5 4.5 0 1 0 0-9M10.3 10.3L14 14",
  triples: "M2 4h12M2 8h12M2 12h12",
  analytics: "M2 14h12M4 11V7M8 11V3M12 11V9",
  versions: "M4 2v12M4 4.5a1.5 1.5 0 1 0 0-3M4 14.5a1.5 1.5 0 1 0 0-3M12 6.5a1.5 1.5 0 1 0 0-3M12 6.5c0 3-8 2-8 5",
  ask: "M8 1.5l1.6 4.4L14 7.5l-4.4 1.6L8 13.5 6.4 9.1 2 7.5l4.4-1.6zM13 1.5v2M12 2.5h2",
  check: "M2 5.5l2 2 4-4.5",
  warn: "M5 1.5v4M5 7.5v.5",
  tasks: "M2.5 4l1.5 1.5L6.5 3M2.5 9l1.5 1.5L6.5 8M9 4h5M9 9.5h5",
  shield: "M8 1.5l5 2v4c0 3-2.2 5.3-5 6.5C5.2 12.8 3 10.5 3 7.5v-4z",
  db: "M8 2c3.3 0 6 .9 6 2s-2.7 2-6 2-6-.9-6-2 2.7-2 6-2zM2 4v8c0 1.1 2.7 2 6 2s6-.9 6-2V4M2 8c0 1.1 2.7 2 6 2s6-.9 6-2",
  chevron: "M2 4.5l4 4 4-4",
  search: "M7 2.5a4.5 4.5 0 1 0 0 9a4.5 4.5 0 1 0 0-9M10.3 10.3L14 14",
  copy: "M5 5h7v7H5zM2.5 10V2.5H10",
  arrow: "M3 7h8M8 4l3 3-3 3",
  box: "M3 5.5l7-3.5 7 3.5v8l-7 3.5-7-3.5zM3 5.5l7 3.5 7-3.5M10 9v8",
  design: "M2.5 13.5l.8-3.2L10.6 3l2.4 2.4-7.3 7.3zM9.4 4.2l2.4 2.4M2.5 13.5h4",
  graph: "M11.5 2.5a1.8 1.8 0 1 0 0 3.6a1.8 1.8 0 1 0 0-3.6M4.5 6.2a1.8 1.8 0 1 0 0 3.6a1.8 1.8 0 1 0 0-3.6M11.5 9.9a1.8 1.8 0 1 0 0 3.6a1.8 1.8 0 1 0 0-3.6M6.1 7.2l3.8-2M6.1 8.8l3.8 2",
  back: "M13 8H3M7 4L3 8l4 4",
};

export function Icon({ name, size = 16, stroke = "currentColor", width = 1.6, style }: { name: string; size?: number; stroke?: string; width?: number; style?: React.CSSProperties }) {
  const box = name === "box" ? 20 : name === "check" || name === "warn" ? 10 : name === "chevron" ? 12 : name === "arrow" ? 14 : name === "copy" ? 14 : 16;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${box} ${box}`} fill="none" aria-hidden="true" style={{ stroke, strokeWidth: width, strokeLinecap: "round", strokeLinejoin: "round", flex: "none", ...style }}>
      <path d={ICON[name] ?? ICON.overview} />
    </svg>
  );
}
