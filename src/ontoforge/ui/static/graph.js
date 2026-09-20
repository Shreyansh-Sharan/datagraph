// Graph stage: sigma.js (WebGL) over a graphology graph, with ForceAtlas2 + noverlap layout.
// Vendored UMD globals: graphology, graphologyLibrary, Sigma (all MIT, see vendor/LICENSE.*).
import { h } from "./ui.js";

const CLASS_COLORS = ["#0b6e4f", "#175cd3", "#b54708", "#7a1fa2", "#b42318", "#0e7490", "#4d7c0f", "#a21caf", "#9a3412", "#1d4ed8", "#0f766e", "#be185d"];

export function palette(keys) {
  const m = new Map();
  [...new Set(keys)].forEach((k, i) => m.set(k, CLASS_COLORS[i % CLASS_COLORS.length]));
  return m;
}

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/**
 * renderGraph(container, opts) -> controller
 * opts: { nodes: [{id, label, type, color?, size?}], edges: [{source, target, label}], selected, onSelect(node), onExpand(node),
 *         onContextMenu(node, items) -> menu items [{label, action}], colorBy: "type" | "community", showEdgeLabels }
 */
export function renderGraph(container, opts) {
  container.replaceChildren();
  container.classList.add("stage");
  const stageEl = h("div", { class: "stage-canvas", role: "img", "aria-label": `Graph with ${opts.nodes.length} nodes and ${opts.edges.length} edges`, tabindex: 0 });
  const toolbar = h("div", { class: "stage-tools", role: "toolbar", "aria-label": "Graph controls" });
  const legend = h("div", { class: "stage-legend" });
  const status = h("div", { class: "stage-status", "aria-live": "polite" });
  const clusterPanel = h("div", { class: "stage-clusters", hidden: true });
  const menu = h("div", { class: "ctx-menu", role: "menu", hidden: true });
  container.append(stageEl, toolbar, legend, status, clusterPanel, menu);

  const graph = new graphology.Graph({ multi: false, type: "directed" });
  const types = palette(opts.nodes.map(n => n.type || "?"));
  for (const n of opts.nodes) {
    if (!graph.hasNode(n.id)) graph.addNode(n.id, { label: n.label || n.id, cls: n.type || "?", color: n.color || types.get(n.type || "?") || "#5a6470", size: n.size || 4, x: Math.random(), y: Math.random() });
  }
  for (const e of opts.edges) {
    if (graph.hasNode(e.source) && graph.hasNode(e.target) && !graph.hasEdge(e.source, e.target)) graph.addEdge(e.source, e.target, { label: e.label || "", size: 1, type: "arrow" });
  }
  sizeByDegree(graph);
  layout(graph);

  let colorBy = opts.colorBy || "type";
  let communities = null;                 // node -> community id
  let resolution = 1.0;
  const collapsed = new Map();            // community id -> super-node id
  const hidden = new Set();               // nodes folded into a super-node
  let highlighted = new Set();            // search hits
  let selected = opts.selected && graph.hasNode(opts.selected) ? opts.selected : null;
  let hovered = null;
  const ink = () => css("--text") || "#1b2026";
  const dimEdge = () => css("--border") || "#d7dbe0";

  const renderer = new Sigma(graph, stageEl, {
    renderEdgeLabels: !!opts.showEdgeLabels,
    labelDensity: 0.08, labelGridCellSize: 80, labelRenderedSizeThreshold: 6,
    labelFont: "system-ui, sans-serif", labelSize: 12, labelColor: { color: ink() },
    edgeLabelSize: 10, edgeLabelColor: { color: css("--muted") || "#5a6470" },
    defaultEdgeType: "arrow", zIndex: true, minCameraRatio: 0.05, maxCameraRatio: 4,
    nodeReducer: (node, data) => {
      const d = { ...data };
      if (hidden.has(node)) { d.hidden = true; return d; }
      if (colorBy === "community" && communities && communities[node] !== undefined) d.color = CLASS_COLORS[communities[node] % CLASS_COLORS.length];
      const focus = hovered || selected;
      if (focus && node !== focus && !graph.areNeighbors(focus, node)) { d.color = mix(d.color, css("--surface") || "#fff", 0.82); d.label = ""; d.zIndex = 0; }
      else d.zIndex = 1;
      if (highlighted.size && !highlighted.has(node) && !focus) { d.color = mix(d.color, css("--surface") || "#fff", 0.75); }
      if (highlighted.has(node)) { d.highlighted = true; d.zIndex = 2; }
      if (node === selected) { d.highlighted = true; d.size = data.size + 3; d.zIndex = 2; }
      return d;
    },
    edgeReducer: (edge, data) => {
      const d = { ...data, color: dimEdge() };
      if (hidden.has(graph.source(edge)) || hidden.has(graph.target(edge))) { d.hidden = true; return d; }
      const focus = hovered || selected;
      if (focus) {
        if (graph.hasExtremity(edge, focus)) { d.color = mix(ink(), dimEdge(), 0.35); d.size = 1.6; d.zIndex = 1; }
        else { d.hidden = graph.order > 60; d.color = mix(dimEdge(), css("--surface") || "#fff", 0.7); }
      }
      return d;
    },
  });

  renderer.on("enterNode", ({ node }) => { hovered = node; stageEl.style.cursor = "pointer"; renderer.refresh(); });
  renderer.on("leaveNode", () => { hovered = null; stageEl.style.cursor = "default"; renderer.refresh(); });
  renderer.on("clickNode", ({ node }) => { select(node); opts.onSelect?.(nodeOf(node)); });
  renderer.on("doubleClickNode", ({ node, event }) => { event.preventSigmaDefault?.(); opts.onExpand?.(nodeOf(node)); });
  renderer.on("clickStage", () => { hideMenu(); if (selected) { selected = null; renderer.refresh(); } });
  renderer.on("rightClickNode", ({ node, event }) => {
    event.preventSigmaDefault?.(); event.original?.preventDefault?.();
    const a = graph.getNodeAttributes(node);
    if (a.superNode) { showMenu(event, [{ label: `Expand cluster (${a.members.length})`, action: () => expandCluster(a.community) }]); return; }
    const base = [{ label: "Expand neighbours", action: () => opts.onExpand?.(nodeOf(node)) }, { label: "Copy IRI", action: () => navigator.clipboard?.writeText(node) }];
    const extra = opts.onContextMenu ? (opts.onContextMenu(nodeOf(node)) || []) : [];
    showMenu(event, [...base, ...extra]);
  });
  stageEl.addEventListener("contextmenu", (e) => e.preventDefault());
  function showMenu(event, items) {
    menu.replaceChildren(...items.map(it => h("button", { type: "button", role: "menuitem", onClick: () => { hideMenu(); it.action(); } }, it.label)));
    const r = container.getBoundingClientRect(); const ev = event.original || event;
    menu.style.left = `${(ev.clientX || 0) - r.left + 2}px`; menu.style.top = `${(ev.clientY || 0) - r.top + 2}px`; menu.hidden = false;
    menu.querySelector("button")?.focus();
  }
  function hideMenu() { menu.hidden = true; }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") hideMenu(); });
  renderer.on("clickNode", ({ node }) => { const a = graph.getNodeAttributes(node); if (a.superNode) { expandCluster(a.community); } });

  function nodeOf(id) { const a = graph.getNodeAttributes(id); return { id, label: a.label, type: a.cls }; }
  function select(id) { selected = graph.hasNode(id) ? id : null; renderer.refresh(); }
  function fit() { renderer.getCamera().animatedReset({ duration: 250 }); }
  function focusOn(id) {
    if (!graph.hasNode(id)) return;
    const pos = renderer.getNodeDisplayData(id);
    if (pos) renderer.getCamera().animate({ x: pos.x, y: pos.y, ratio: Math.min(renderer.getCamera().ratio, 0.5) }, { duration: 300 });
  }
  function relayout() { layout(graph, true); renderer.refresh(); fit(); }
  function detectClusters() {
    const ug = new graphology.Graph({ type: "undirected" });
    graph.forEachNode((n, a) => { if (!a.superNode) ug.addNode(n, a); });
    graph.forEachEdge((e, a, s, t) => { if (ug.hasNode(s) && ug.hasNode(t) && !ug.hasEdge(s, t)) ug.addEdge(s, t); });
    communities = ug.order ? graphologyLibrary.communitiesLouvain(ug, { resolution }) : {};
    const count = new Set(Object.values(communities)).size;
    status.textContent = `${count} clusters (Louvain, resolution ${resolution})`;
    clusterPanel.hidden = false;
    renderClusters();
  }
  function clearClusters() {
    expandAll(); communities = null; colorBy = "type"; colorSel.value = "type"; clusterPanel.hidden = true;
    status.textContent = `${graph.order} nodes · ${graph.size} edges`; renderLegend(); renderer.refresh();
  }
  function setColorBy(mode) {
    colorBy = mode;
    if (mode === "community" && !communities) detectClusters();
    renderLegend();
    renderer.refresh();
  }
  function membersOf(c) { return Object.entries(communities || {}).filter(([n, cc]) => cc === c).map(([n]) => n); }
  function collapseCluster(c) {
    if (collapsed.has(c)) return;
    const members = membersOf(c); if (members.length < 2) return;
    let x = 0, y = 0; members.forEach(m => { x += graph.getNodeAttribute(m, "x"); y += graph.getNodeAttribute(m, "y"); hidden.add(m); });
    const id = `__cluster_${c}`;
    graph.addNode(id, { label: `Cluster ${c} · ${members.length}`, cls: "cluster", color: CLASS_COLORS[c % CLASS_COLORS.length], size: 8 + Math.min(20, Math.sqrt(members.length) * 3),
      x: x / members.length, y: y / members.length, superNode: true, community: c, members });
    const seen = new Set();
    for (const m of members) graph.forEachEdge(m, (e, a, src, tgt) => {
      const other = src === m ? tgt : src; if (members.includes(other) || hidden.has(other)) return;
      const key = src === m ? `${id}>${other}` : `${other}>${id}`; if (seen.has(key)) return; seen.add(key);
      const [s2, t2] = src === m ? [id, other] : [other, id]; if (!graph.hasEdge(s2, t2)) graph.addEdge(s2, t2, { label: "", size: 1, type: "arrow", synthetic: true });
    });
    collapsed.set(c, id); renderClusters(); renderer.refresh();
  }
  function expandCluster(c) {
    const id = collapsed.get(c); if (!id) return;
    graph.getNodeAttribute(id, "members").forEach(m => hidden.delete(m));
    graph.dropNode(id); collapsed.delete(c); renderClusters(); renderer.refresh();
  }
  function expandAll() { [...collapsed.keys()].forEach(expandCluster); }
  function renderClusters() {
    if (!communities) return;
    const counts = {};
    Object.values(communities).forEach(c => { counts[c] = (counts[c] || 0) + 1; });
    const ids = Object.keys(counts).map(Number).sort((a, b) => counts[b] - counts[a]);
    clusterPanel.replaceChildren(
      h("div", { class: "row" }, h("strong", {}, `${ids.length} clusters`),
        h("label", { class: "check small" }, "resolution ", h("input", { type: "range", min: 0.2, max: 3, step: 0.1, value: resolution, "aria-label": "Cluster resolution",
          onChange: e => { resolution = Number(e.target.value); expandAll(); detectClusters(); renderLegend(); renderer.refresh(); } })),
        h("label", { class: "check small" }, h("input", { type: "checkbox", checked: colorBy === "community", onChange: e => { setColorBy(e.target.checked ? "community" : "type"); colorSel.value = colorBy; } }), "colour by cluster"),
        h("button", { type: "button", class: "sm", onClick: () => ids.forEach(collapseCluster) }, "Collapse all"),
        h("button", { type: "button", class: "sm", onClick: expandAll }, "Expand all"),
        h("button", { type: "button", class: "sm ghost", onClick: clearClusters }, "Clear")),
      h("div", { class: "chips" }, ids.map(c => h("button", { type: "button", class: "chip" + (collapsed.has(c) ? " collapsed" : ""), title: collapsed.has(c) ? "Expand cluster" : "Collapse into a super-node",
        onClick: () => collapsed.has(c) ? expandCluster(c) : collapseCluster(c) },
        h("i", { style: { background: CLASS_COLORS[c % CLASS_COLORS.length] } }), `${c} · ${counts[c]}`))));
  }
  function renderLegend() {
    legend.replaceChildren();
    if (colorBy === "type") {
      const counts = {};
      graph.forEachNode((n, a) => { counts[a.cls] = (counts[a.cls] || 0) + 1; });
      for (const [t, c] of Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 12)) {
        legend.append(h("span", { class: "swatch" }, h("i", { style: { background: types.get(t) } }), `${t.split(/[#/]/).pop()} ${c}`));
      }
    } else if (communities) {
      const counts = {};
      Object.values(communities).forEach(c => { counts[c] = (counts[c] || 0) + 1; });
      for (const [c, n] of Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 12)) {
        legend.append(h("span", { class: "swatch" }, h("i", { style: { background: CLASS_COLORS[c % CLASS_COLORS.length] } }), `community ${c} · ${n}`));
      }
    }
  }
  const btn = (label, title, fn) => h("button", { type: "button", class: "sm", title, "aria-label": title, onClick: fn }, label);
  const colorSel = h("select", { class: "sm", "aria-label": "Color nodes by", onChange: e => setColorBy(e.target.value) },
    h("option", { value: "type", selected: colorBy === "type" }, "Color: class"), h("option", { value: "community", selected: colorBy === "community" }, "Color: community"));
  const labelsToggle = h("label", { class: "check small" }, h("input", { type: "checkbox", checked: !!opts.showEdgeLabels, onChange: e => { renderer.setSetting("renderEdgeLabels", e.target.checked); } }), "edge labels");
  toolbar.append(btn("+", "Zoom in", () => renderer.getCamera().animatedZoom({ duration: 200 })), btn("−", "Zoom out", () => renderer.getCamera().animatedUnzoom({ duration: 200 })),
    btn("Fit", "Fit graph to view", fit), btn("Layout", "Run the layout again", relayout), btn("Clusters", "Detect clusters (Louvain) on the displayed graph", () => { detectClusters(); setColorBy("community"); colorSel.value = "community"; }),
    colorSel, labelsToggle);
  stageEl.addEventListener("keydown", (ev) => {
    const ids = graph.nodes(); if (!ids.length) return;
    const i = ids.indexOf(selected);
    if (ev.key === "ArrowRight" || ev.key === "ArrowDown") { const n = ids[(i + 1) % ids.length]; select(n); focusOn(n); opts.onSelect?.(nodeOf(n)); ev.preventDefault(); }
    if (ev.key === "ArrowLeft" || ev.key === "ArrowUp") { const n = ids[(i - 1 + ids.length) % ids.length]; select(n); focusOn(n); opts.onSelect?.(nodeOf(n)); ev.preventDefault(); }
    if (ev.key === "Enter" && selected) opts.onExpand?.(nodeOf(selected));
    if (ev.key === "f") fit();
  });
  const ro = new ResizeObserver(() => renderer.refresh());
  ro.observe(container);
  renderLegend();
  if (colorBy === "community") setColorBy("community");
  status.textContent = status.textContent || `${graph.order} nodes · ${graph.size} edges`;
  setTimeout(fit, 0);

  return {
    destroy: () => { ro.disconnect(); renderer.kill(); },
    select: (id) => { select(id); focusOn(id); },
    fit,
    highlight: (ids) => {   // search hits: emphasise them and their neighbours, zoom to the first
      highlighted = new Set(ids.filter(id => graph.hasNode(id)));
      renderer.refresh();
      if (highlighted.size) focusOn([...highlighted][0]);
    },
    clearHighlight: () => { highlighted = new Set(); renderer.refresh(); },
    has: (id) => graph.hasNode(id),
    merge: ({ nodes, edges }) => {   // add a neighbourhood without discarding the current picture
      const t2 = palette([...graph.mapNodes((n, a) => a.cls), ...nodes.map(n => n.type || "?")]);
      for (const n of nodes) if (!graph.hasNode(n.id)) graph.addNode(n.id, { label: n.label || n.id, cls: n.type || "?", color: t2.get(n.type || "?"), size: 4, x: Math.random(), y: Math.random() });
      for (const e of edges) if (graph.hasNode(e.source) && graph.hasNode(e.target) && !graph.hasEdge(e.source, e.target)) graph.addEdge(e.source, e.target, { label: e.label || "", size: 1, type: "arrow" });
      graph.forEachNode((n, a) => { if (!types.has(a.cls)) types.set(a.cls, t2.get(a.cls)); graph.setNodeAttribute(n, "color", types.get(a.cls)); });
      sizeByDegree(graph); layout(graph, true); communities = null; if (colorBy === "community") setColorBy("community"); renderLegend();
      status.textContent = `${graph.order} nodes · ${graph.size} edges`; renderer.refresh();
    },
    graph,
  };
}

function sizeByDegree(graph) {
  let max = 1;
  graph.forEachNode(n => { max = Math.max(max, graph.degree(n)); });
  graph.forEachNode(n => graph.setNodeAttribute(n, "size", 3 + 9 * Math.sqrt(graph.degree(n) / max)));
}

function layout(graph, incremental = false) {
  if (!graph.order) return;
  if (!incremental) graphologyLibrary.layout.circular.assign(graph, { scale: 100 });
  const settings = graphologyLibrary.layoutForceAtlas2.inferSettings(graph);
  const iterations = graph.order > 2000 ? 60 : graph.order > 500 ? 150 : 300;
  graphologyLibrary.layoutForceAtlas2.assign(graph, { iterations, settings: { ...settings, gravity: 1, scalingRatio: 4, barnesHutOptimize: graph.order > 300, adjustSizes: false } });
  graphologyLibrary.layoutNoverlap.assign(graph, { maxIterations: 60, settings: { margin: 4, ratio: 1.2 } });
}

function mix(a, b, t) {   // hex colors, t = share of b
  const p = (c) => [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)];
  try { const [x, y] = [p(a), p(b)]; return "#" + x.map((v, i) => Math.round(v * (1 - t) + y[i] * t).toString(16).padStart(2, "0")).join(""); } catch { return a; }
}
