// Explore: the whole graph as a quiet backdrop, the focused neighbourhood in colour, details beside.
import { api, local, qs } from "../api.js";
import { h, append, button, input, select, field, dialog, toast, errorToast, badge, table, empty, skeleton, fmtNum } from "../ui.js";
import { renderGraph, palette } from "../graph.js";
import { iconEl } from "../icons.js";

export async function exploreTab(ctx) {
  const { version } = ctx; const vid = version.id;
  const status = await api.get(`/versions/${vid}/graph/status`);
  if (!status.triples) return empty("The graph is empty", "Build the knowledge graph first.", h("a", { class: "btn", href: `#/d/${encodeURIComponent(ctx.name)}/build` }, "Go to build"));
  const onto = version.has_ontology ? await api.get(`/versions/${vid}/ontology`).catch(() => null) : null;
  const glyph = (t) => onto?.classes.find(c => c.iri === t)?.icon || "";
  const typeName = (t) => { const c = onto?.classes.find(c => c.iri === t); return c?.label || local(t); };
  const types = Object.keys(status.types);
  const root = h("div", { class: "explore" });

  // -- controls ------------------------------------------------------------
  const q = input({ type: "search", placeholder: "Find by label or IRI", "aria-label": "Search entities" });
  const typeSel = select([{ value: "", label: "All types" }, ...types.map(t => ({ value: t, label: `${glyph(t)} ${typeName(t)} (${fmtNum(status.types[t])})`.trim() }))], { "aria-label": "Entity type" });
  const fieldSel = select([{ value: "any", label: "label or IRI" }, { value: "label", label: "label" }, { value: "iri", label: "IRI" }], { "aria-label": "Search field" });
  const matchSel = select([{ value: "contains", label: "contains" }, { value: "exact", label: "exact" }, { value: "starts_with", label: "starts with" }, { value: "ends_with", label: "ends with" }], { "aria-label": "Match type" });
  const depth = select(["1", "2", "3"], { value: "2", "aria-label": "Neighbourhood depth" });
  const labels = h("input", { type: "checkbox", checked: true, "aria-label": "Show labels" });
  const edges = h("input", { type: "checkbox", checked: true, "aria-label": "Show edges" });
  const orphans = h("input", { type: "checkbox", "aria-label": "Hide orphans" });
  const results = h("div", { class: "results" });
  const stage = h("div", { class: "graph stage-host fill" });
  const drawer = h("aside", { class: "drawer", "aria-label": "Entity detail" }, h("div", { class: "drawer-empty" }, iconEl("explore"), h("p", { class: "muted" }, "Find an entity or click a node to see its details.")));
  let graph = null, current = ctx.arg || null;

  root.append(
    h("div", { class: "page-head compact" },
      h("div", {}, h("h1", {}, "Explore"), h("p", { class: "muted small" }, `${fmtNum(status.triples)} triples · ${types.length} types`)),
      h("form", { class: "searchbar", onSubmit: e => { e.preventDefault(); search(); } }, q, typeSel, fieldSel, matchSel,
        h("label", { class: "check small" }, "depth", depth), button([iconEl("search"), "Find"], { class: "primary", type: "submit" })),
      h("div", { class: "row small toggles" },
        h("label", { class: "check" }, labels, "Labels"), h("label", { class: "check" }, edges, "Edges"), h("label", { class: "check" }, orphans, "Hide orphans"),
        h("a", { class: "btn sm", href: `#/d/${encodeURIComponent(ctx.name)}/triples` }, iconEl("triples"), "Triples"))),
    results,
    h("div", { class: "explore-body" }, stage, drawer));
  labels.addEventListener("change", () => graph?.setting("renderLabels", labels.checked));
  edges.addEventListener("change", () => graph?.setting("hideEdges", !edges.checked));
  orphans.addEventListener("change", () => graph?.setting("hideOrphans", orphans.checked));

  const node = (n) => ({ id: n.iri, label: n.label, type: n.types[0] || "?", glyph: glyph(n.types[0]) });
  const edge = (e) => ({ source: e.source, target: e.target, label: local(e.predicate) });
  const handlers = () => ({
    onSelect: n => show(n.id, { keep: true }),
    onExpand: n => expand(n.id),
    onContextMenu: n => [
      { label: "Show details", action: () => show(n.id, { keep: true }) },
      { label: "Compute virtual attributes", action: () => virtual(n.id) },
      { label: "Datasets", action: () => datasets(n.id) },
      { label: "Bridges", action: () => bridges(n.id) },
    ],
  });

  async function overview() {
    try {
      const sub = await api.get(`/versions/${vid}/graph/overview?limit=1500`);
      graph?.destroy?.();
      graph = renderGraph(stage, { nodes: sub.nodes.map(node), edges: sub.edges.map(edge), backdrop: true, ...handlers() });
      graph.setting("renderLabels", labels.checked);
    } catch (e) { errorToast(e); }
  }

  async function search() {
    results.replaceChildren(skeleton(1));
    try {
      const hits = await api.get(`/versions/${vid}/graph/search${qs({ q: q.value, type: typeSel.value, field: fieldSel.value, match: matchSel.value, limit: 30 })}`);
      results.replaceChildren(hits.length
        ? h("ul", { class: "hits" }, hits.map(e => h("li", {}, h("button", { type: "button", class: "hit", onClick: () => show(e.iri) },
            h("span", { class: "hit-glyph" }, glyph(e.types[0])), h("span", { class: "hit-label" }, e.label), h("span", { class: "hit-type" }, typeName(e.types[0] || ""))))))
        : h("p", { class: "muted small" }, "No entities match."));
      if (hits.length) show(hits[0].iri);
    } catch (e) { errorToast(e); results.replaceChildren(); }
  }

  async function show(iri, { keep = false } = {}) {
    current = iri;
    drawer.replaceChildren(skeleton(6));
    try {
      const e = await api.get(`/versions/${vid}/graph/entity${qs({ iri })}`);
      const att = e.attachments || {};
      const t0 = e.types[0] || "";
      const relRow = (r, out) => {
        const other = out ? r.target : r.source;
        return h("li", {}, iconEl(out ? "arrowRight" : "arrowLeft", "muted"), h("span", { class: "muted" }, local(r.predicate)), " ",
          h("button", { type: "button", class: "link", onClick: () => show(other) }, `${glyphOf(other)} ${local(other)}`.trim()), r.inferred ? badge("inferred", "neutral") : null);
      };
      const grouped = (rels, out) => {
        const by = {};
        rels.forEach(r => (by[r.predicate] ||= []).push(r));
        return Object.entries(by).map(([p, rs]) => h("details", { open: rs.length <= 6 }, h("summary", {}, local(p), " ", h("span", { class: "muted" }, rs.length)),
          h("ul", { class: "rel-list" }, rs.slice(0, 40).map(r => relRow(r, out)), rs.length > 40 ? h("li", { class: "muted small" }, `… ${rs.length - 40} more`) : null)));
      };
      drawer.replaceChildren();
      append(drawer, [
        h("div", { class: "drawer-head" }, h("div", { class: "drawer-glyph" }, glyph(t0) || iconEl("id")),
          h("div", {}, h("h2", {}, e.label), h("code", { class: "small muted iri" }, e.iri))),
        h("div", { class: "row drawer-actions" },
          button([iconEl("expand"), "Expand"], { class: "sm", title: "Add this entity's neighbourhood to the graph", onClick: () => expand(iri) }),
          button([iconEl("explore"), "Focus"], { class: "sm ghost", title: "Rebuild the picture around this entity", onClick: () => focus(iri) })),
        h("section", {}, h("h3", {}, iconEl("info"), "Entity"),
          h("dl", { class: "attrs" }, h("dt", {}, "Type"), h("dd", {}, e.types.map(t => badge(`${glyph(t)} ${typeName(t)}`.trim(), "neutral"))),
            h("dt", {}, "ID"), h("dd", {}, h("code", { class: "small" }, local(e.iri))))),
        e.attributes.length ? h("section", {}, h("h3", {}, iconEl("tag"), `Attributes · ${e.attributes.length}`),
          h("dl", { class: "attrs" }, e.attributes.map(a => [h("dt", {}, local(a.predicate)), h("dd", {}, a.value, a.inferred ? badge("inferred", "neutral") : null)]))) : null,
        e.outgoing.length ? h("section", {}, h("h3", {}, iconEl("arrowRight"), `Outgoing · ${e.outgoing.length}`), grouped(e.outgoing, true)) : null,
        e.incoming.length ? h("section", {}, h("h3", {}, iconEl("arrowLeft"), `Incoming · ${e.incoming.length}`), grouped(e.incoming, false)) : null,
        (att.virtual_attributes?.length || att.actions?.length || att.datasets?.length || att.bridges?.length) ? h("section", {}, h("h3", {}, iconEl("key"), "More"),
          h("div", { class: "row" },
            att.virtual_attributes?.length ? button("Virtual attributes", { class: "sm", onClick: () => virtual(iri) }) : null,
            ...(att.actions || []).map(a => button(a, { class: "sm", onClick: () => action(iri, a) })),
            att.datasets?.length ? button("Datasets", { class: "sm", onClick: () => datasets(iri) }) : null,
            att.bridges?.length ? button("Bridges", { class: "sm", onClick: () => bridges(iri) }) : null)) : null]);
      if (graph?.has(iri)) { graph.select(iri); if (!keep) expand(iri); } else focus(iri);
    } catch (err) { errorToast(err); }
  }
  const glyphOf = (iri) => { const n = graph?.attrs?.(iri); return n?.glyph || ""; };

  async function neighbourhood(iri) {
    const sub = await api.get(`/versions/${vid}/graph/neighbourhood${qs({ iri, depth: depth.value, limit: 300 })}`);
    return { nodes: sub.nodes.map(node), edges: sub.edges.map(edge) };
  }
  async function expand(iri) {   // add the neighbourhood into the current picture and light it up
    try { const sub = await neighbourhood(iri); if (!graph) return focus(iri); graph.merge(sub); graph.select(iri); } catch (e) { errorToast(e); }
  }
  async function focus(iri) {    // rebuild around one entity
    try { const sub = await neighbourhood(iri); graph?.destroy?.(); graph = renderGraph(stage, { ...sub, selected: iri, ...handlers() }); graph.setting("renderLabels", labels.checked); }
    catch (e) { errorToast(e); }
  }
  async function virtual(iri) { try { const v = await api.get(`/versions/${vid}/graph/entity/virtual${qs({ iri })}`); dialog("Virtual attributes", table([{ label: "Name", key: "k" }, { label: "Value", render: r => r.v ?? "—" }], Object.entries(v).map(([k, v]) => ({ k, v }))), { confirm: "Close", cancel: "Dismiss" }); } catch (e) { errorToast(e); } }
  async function action(iri, name) { try { const r = await api.post(`/versions/${vid}/graph/entity/actions/${encodeURIComponent(name)}${qs({ iri })}`);
    dialog(`Action: ${name}`, r.kind === "scalar" ? h("p", {}, h("strong", {}, r.value ?? "—")) : r.rows.length ? table(r.columns.map(c => ({ label: c, render: row => row[c] ?? "—" })), r.rows) : h("p", {}, "No rows."), { confirm: "Close", cancel: "Dismiss" }); } catch (e) { errorToast(e); } }
  async function datasets(iri) { try { const ds = await api.get(`/versions/${vid}/graph/entity/datasets${qs({ iri })}`);
    dialog("Datasets", h("div", {}, ds.length ? ds.map(d => h("div", {}, h("h3", {}, d.table, " ", h("span", { class: "muted small" }, d.description || "")), d.rows.length ? table(d.columns.map(c => ({ label: c, render: r => r[c] ?? "—" })), d.rows) : h("p", { class: "muted small" }, "No rows."))) : h("p", { class: "muted" }, "No datasets are attached to this class.")), { confirm: "Close", cancel: "Dismiss" }); } catch (e) { errorToast(e); } }
  async function bridges(iri) { try { const b = await api.get(`/versions/${vid}/graph/entity/bridges${qs({ iri })}`);
    dialog("Bridges", b.length ? table([{ label: "Domain", key: "domain" }, { label: "Entity", render: x => x.error ? badge(x.error, "error") : h("a", { href: `#/d/${encodeURIComponent(x.domain)}/explore/${encodeURIComponent(x.iri)}` }, x.label || local(x.iri)) }, { label: "Exists", render: x => x.exists ? badge("yes", "ok") : badge("no", "neutral") }], b) : h("p", { class: "muted" }, "No bridges for this class."), { confirm: "Close", cancel: "Dismiss" }); } catch (e) { errorToast(e); } }

  // sigma sizes itself on creation: wait until the router has attached this view to the document
  setTimeout(async () => { await overview(); if (current) show(current, { keep: true }); }, 0);
  return root;
}
