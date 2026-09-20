// A small inline SVG icon set (own drawings, 16px grid, stroke-based). Use: icon("graph").
const PATHS = {
  info: "M8 1.5a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13zM8 7v4M8 5v.01",
  table: "M2 3h12v10H2zM2 7h12M6 3v10",
  ontology: "M8 2v3M4 14v-3M12 14v-3M3 5h10M4 11a1.5 1.5 0 1 0 0-.01M12 11a1.5 1.5 0 1 0 0-.01M8 5a1.5 1.5 0 1 0 0-.01M4 11l4-6 4 6",
  mapping: "M2 4h4v3H2zM2 9h4v3H2zM10 6.5h4v3h-4zM6 5.5h2.5M6 10.5h2.5M8.5 5.5v5",
  rules: "M9 1.5L3.5 9H8l-1 5.5L12.5 7H8z",
  quality: "M8 1.5l5.5 2v4c0 3.5-2.5 6-5.5 7-3-1-5.5-3.5-5.5-7v-4zM5.5 8l2 2 3-3.5",
  build: "M3 12.5h10M4 12.5V7h2v5.5M7 12.5V4h2v8.5M10 12.5V9h2v3.5",
  explore: "M11 5a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM3 13l2.5-2.5M13 13l-2.5-2.5M5 3a1.5 1.5 0 1 0 0-.01M11 3a1.5 1.5 0 1 0 0-.01",
  triples: "M2 4h2M6 4h8M2 8h2M6 8h8M2 12h2M6 12h8",
  analytics: "M2 13h12M3 10l3-3 3 2 4-5",
  settings: "M8 5a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.5 3.5l1.5 1.5M11 11l1.5 1.5M3.5 12.5L5 11M11 5l1.5-1.5",
  overview: "M2 2h5v5H2zM9 2h5v5H9zM2 9h5v5H2zM9 9h5v5H9z",
  domain: "M2 4.5l6-3 6 3v7l-6 3-6-3zM8 7.5v7M2 4.5l6 3 6-3",
  check: "M3 8.5l3 3 7-7",
  search: "M7 2.5a4.5 4.5 0 1 1 0 9 4.5 4.5 0 0 1 0-9zM10.5 10.5L14 14",
  arrowRight: "M3 8h10M9 4l4 4-4 4",
  arrowLeft: "M13 8H3M7 4L3 8l4 4",
  id: "M2 4h12v8H2zM5 7v2M8 6.5h3v3H8z",
  tag: "M2 2h6l6 6-6 6-6-6zM5 5a.5.5 0 1 0 0-.01",
  key: "M10 2.5a3.5 3.5 0 1 1-2.5 6L3 13H1.5v-1.5L6.5 7A3.5 3.5 0 0 1 10 2.5zM10.5 5a.5.5 0 1 0 0-.01",
  list: "M5 4h9M5 8h9M5 12h9M2 4h.01M2 8h.01M2 12h.01",
  sun: "M8 4.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zM8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3 3l1 1M12 12l1 1M3 13l1-1M12 4l1-1",
  moon: "M13 9.5A5.5 5.5 0 0 1 6.5 3 5.5 5.5 0 1 0 13 9.5z",
  tasks: "M3 4h2M7 4h6M3 8h2M7 8h6M3 12h2M7 12h6",
  shield: "M8 1.5l5.5 2v4c0 3.5-2.5 6-5.5 7-3-1-5.5-3.5-5.5-7v-4z",
  expand: "M2 6V2h4M14 6V2h-4M2 10v4h4M14 10v4h-4",
  cluster: "M5 5a2 2 0 1 0 0-.01M11 5a2 2 0 1 0 0-.01M8 11.5a2 2 0 1 0 0-.01M6.5 6.5l1 3M9.5 6.5l-1 3",
};

export function icon(name, cls = "") {
  const d = PATHS[name] || PATHS.info;
  return `<svg class="ico ${cls}" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${d}"/></svg>`;
}
export const iconEl = (name, cls = "") => { const t = document.createElement("template"); t.innerHTML = icon(name, cls); return t.content.firstChild; };
