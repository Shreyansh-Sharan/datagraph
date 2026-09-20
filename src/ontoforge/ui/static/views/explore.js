// Explore: a full-width graph stage with a search bar above and an entity drawer beside it.
import { api, local, qs } from "../api.js";
import { h, append, button, input, select, field, dialog, toast, errorToast, badge, table, empty, skeleton } from "../ui.js";
import { renderGraph, palette } from "../graph.js";

export async function exploreTab(ctx) {
  const { version } = ctx; const vid = version.id;
  const status = await api.get(`/versions/${vid}/graph/status`);
  if (!status.triples) return empty("The graph is empty", "Build the knowledge graph first.", h("a", { class: "btn", href: `#/d/${encodeURIComponent(ctx.name)}/build` }, "Go to build"));
  const types = Object.keys(status.types);
  const root = h("div", { class: "explore" });
  const q = input({ type: "search", placeholder: "Find by label or IRI", "aria-label": "Search entities" });
  const typeSel = select([{ value: "", label: "All types" }, ...types.map(t => ({ value: t, label: `${local(t)} (${status.types[t].toLocaleString()})` }))], { "aria-label": "Entity type" });
  const fieldSel = select([{ value: "any", label: "label or IRI" }, { value: "label", label: "label" }, { value: "iri", label: "IRI" }], { "aria-label": "Search field" });
  const matchSel = select([{ value: "contains", label: "contains" }, { value: "exact", label: "exact" }, { value: "starts_with", label: "starts with" }, { value: "ends_with", label: "ends with" }], { "aria-label": "Match type" });
  const depth = select(["1", "2", "3"], { value: "2", "aria-label": "Neighbourhood depth" });
  const results = h("div", { class: "results", role: "region", "aria-label": "Search results" });
  const stage = h("div", { class: "graph stage-host" });
  const drawer = h("aside", { class: "drawer", "aria-label": "Entity detail" }, h("p", { class: "muted" }, "Search for an entity, or click a node."));
  let graph = null, current = ctx.arg || null;

  root.append(
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Explore"), h("p", { class: "muted" }, `${status.triples.toLocaleString()} triples · ${types.length} types`)),
      h("div", { class: "actions" }, h("form", { class: "searchbar", onSubmit: e => { e.preventDefault(); search(); } }, q, typeSel, fieldSel, matchSel,
        h("label", { class: "check small" }, "depth", depth), button("Find", { class: "primary", type: "submit" }), h("a", { class: "btn", href: `#/d/${encodeURIComponent(ctx.name)}/triples` }, "Triples")))),
    results,
    h("div", { class: "explore-body" }, stage, drawer));

  async function search(initial = false) {
    results.replaceChildren(skeleton(2));
    try {
      const hits = await api.get(`/versions/${vid}/graph/search${qs({ q: q.value, type: typeSel.value, field: fieldSel.value, match: matchSel.value, limit: 30 })}`);
      results.replaceChildren(hits.length
        ? h("ul", { class: "hits" }, hits.map(e => h("li", {}, h("button", { type: "button", class: "hit", onClick: () => show(e.iri) },
            h("span", { class: "hit-label" }, e.label), h("span", { class: "hit-type" }, e.types.map(local).join(", "))))))
        : h("p", { class: "muted small" }, "No entities match."));
      if (initial) return;
      if (graph) graph.highlight(hits.map(e => e.iri));            // emphasise matches already on the stage
      if (hits.length) show(hits[0].iri, { keep: hits.some(e => graph?.has(e.iri)) });
    } catch (e) { errorToast(e); results.replaceChildren(); }
  }

  async function show(iri, { keep = false } = {}) {
    current = iri;
    drawer.replaceChildren(skeleton(6));
    try {
      const e = await api.get(`/versions/${vid}/graph/entity${qs({ iri })}`);
      const att = e.attachments || {};
      const rel = (r, out) => h("li", {}, h("button", { type: "button", class: "link", onClick: () => show(out ? r.target : r.source) }, local(out ? r.target : r.source)),
        h("span", { class: "muted small" }, out ? ` ← ${local(r.predicate)}` : ` ${local(r.predicate)} →`), r.inferred ? badge("inferred", "neutral") : null);
      const grouped = (rels, out) => {
        const by = {};
        rels.forEach(r => (by[r.predicate] ||= []).push(r));
        return Object.entries(by).map(([p, rs]) => h("details", { open: rs.length <= 8 }, h("summary", {}, `${local(p)} ${out ? "→" : "←"} `, h("span", { class: "muted" }, rs.length)),
          h("ul", { class: "rel-list" }, rs.slice(0, 50).map(r => rel(r, out)), rs.length > 50 ? h("li", { class: "muted small" }, `… ${rs.length - 50} more`) : null)));
      };
      drawer.replaceChildren();
      append(drawer, [
        h("div", { class: "drawer-head" }, h("h2", {}, e.label), h("div", { class: "row" }, e.types.map(t => badge(local(t), "neutral"))), h("code", { class: "small muted iri" }, e.iri),
          h("div", { class: "row" }, button("Expand", { class: "sm", title: "Add this entity's neighbourhood to the graph", onClick: () => expand(iri, true) }), button("Focus", { class: "sm ghost", onClick: () => expand(iri, false) }))),
        e.attributes.length ? h("dl", { class: "attrs" }, e.attributes.map(a => [h("dt", {}, local(a.predicate)), h("dd", {}, a.value, a.inferred ? badge("inferred", "neutral") : null)])) : h("p", { class: "muted small" }, "No attributes."),
        e.outgoing.length ? h("section", {}, h("h3", {}, `Outgoing · ${e.outgoing.length}`), grouped(e.outgoing, true)) : null,
        e.incoming.length ? h("section", {}, h("h3", {}, `Incoming · ${e.incoming.length}`), grouped(e.incoming, false)) : null,
        (att.virtual_attributes?.length || att.actions?.length || att.datasets?.length || att.bridges?.length) ? h("section", {}, h("h3", {}, "More"),
          h("div", { class: "row" },
            att.virtual_attributes?.length ? button("Virtual attributes", { class: "sm", onClick: () => virtual(iri) }) : null,
            ...(att.actions || []).map(a => button(a, { class: "sm", onClick: () => action(iri, a) })),
            att.datasets?.length ? button("Datasets", { class: "sm", onClick: () => datasets(iri) }) : null,
            att.bridges?.length ? button("Bridges", { class: "sm", onClick: () => bridges(iri) }) : null)) : null]);
      if (keep && graph) graph.select(iri); else expand(iri, false);
    } catch (err) { errorToast(err); }
  }

  async function expand(iri, merge) {
    try {
      const sub = await api.get(`/versions/${vid}/graph/neighbourhood${qs({ iri, depth: depth.value, limit: 300 })}`);
      const nodes = sub.nodes.map(n => ({ id: n.iri, label: n.label, type: n.types[0] || "?" }));
      const edges = sub.edges.map(e => ({ source: e.source, target: e.target, label: local(e.predicate) }));
      if (merge && graph) { graph.merge({ nodes, edges }); graph.select(iri); return; }
      graph?.destroy?.();
      graph = renderGraph(stage, { nodes, edges, selected: iri, ...handlers() });
    } catch (e) { errorToast(e); }
  }
  const handlers = () => ({
    onSelect: n => show(n.id, { keep: true }),
    onExpand: n => expand(n.id, true),
    onContextMenu: n => [
      { label: "Show details", action: () => show(n.id, { keep: true }) },
      { label: "Focus (rebuild around it)", action: () => expand(n.id, false) },
      { label: "Compute virtual attributes", action: () => virtual(n.id) },
      { label: "Datasets", action: () => datasets(n.id) },
      { label: "Bridges", action: () => bridges(n.id) },
    ],
  });
  async function overview() {
    try {
      const sub = await api.get(`/versions/${vid}/graph/overview?limit=300`);
      const nodes = sub.nodes.map(n => ({ id: n.iri, label: n.label, type: n.types[0] || "?" }));
      const edges = sub.edges.map(e => ({ source: e.source, target: e.target, label: local(e.predicate) }));
      graph?.destroy?.();
      graph = renderGraph(stage, { nodes, edges, ...handlers() });
    } catch (e) { errorToast(e); }
  }
  async function virtual(iri) { try { const v = await api.get(`/versions/${vid}/graph/entity/virtual${qs({ iri })}`); dialog("Virtual attributes", table([{ label: "Name", key: "k" }, { label: "Value", render: r => r.v ?? "—" }], Object.entries(v).map(([k, v]) => ({ k, v }))), { confirm: "Close", cancel: "Dismiss" }); } catch (e) { errorToast(e); } }
  async function action(iri, name) { try { const r = await api.post(`/versions/${vid}/graph/entity/actions/${encodeURIComponent(name)}${qs({ iri })}`);
    dialog(`Action: ${name}`, r.kind === "scalar" ? h("p", {}, h("strong", {}, r.value ?? "—")) : r.rows.length ? table(r.columns.map(c => ({ label: c, render: row => row[c] ?? "—" })), r.rows) : h("p", {}, "No rows."), { confirm: "Close", cancel: "Dismiss" }); } catch (e) { errorToast(e); } }
  async function datasets(iri) { try { const ds = await api.get(`/versions/${vid}/graph/entity/datasets${qs({ iri })}`);
    dialog("Datasets", h("div", {}, ds.map(d => h("div", {}, h("h3", {}, d.table, " ", h("span", { class: "muted small" }, d.description || "")), d.rows.length ? table(d.columns.map(c => ({ label: c, render: r => r[c] ?? "—" })), d.rows) : h("p", { class: "muted small" }, "No rows.")))), { confirm: "Close", cancel: "Dismiss" }); } catch (e) { errorToast(e); } }
  async function bridges(iri) { try { const b = await api.get(`/versions/${vid}/graph/entity/bridges${qs({ iri })}`);
    dialog("Bridges", table([{ label: "Domain", key: "domain" }, { label: "Entity", render: x => x.error ? badge(x.error, "error") : h("a", { href: `#/d/${encodeURIComponent(x.domain)}/explore/${encodeURIComponent(x.iri)}` }, x.label || local(x.iri)) }, { label: "Exists", render: x => x.exists ? badge("yes", "ok") : badge("no", "neutral") }], b), { confirm: "Close", cancel: "Dismiss" }); } catch (e) { errorToast(e); } }

  if (current) show(current); else overview();
  return root;
}
