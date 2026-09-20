// Explore: search entities, inspect one (attributes, relations, actions, virtual attributes, datasets, bridges), expand neighbourhood.
import { api, local, qs } from "../api.js";
import { h, button, input, select, field, dialog, toast, errorToast, badge, table, empty, skeleton, fmtNum } from "../ui.js";
import { renderGraph, palette } from "../graph.js";

export async function exploreTab(ctx) {
  const { version } = ctx; const vid = version.id;
  const status = await api.get(`/versions/${vid}/graph/status`);
  if (!status.triples) return empty("The graph is empty", "Build the knowledge graph first.", h("a", { class: "btn", href: `#/d/${encodeURIComponent(ctx.name)}/build` }, "Go to build"));
  const types = Object.keys(status.types);
  const colors = palette(types);
  const root = h("div", {});
  const q = input({ type: "search", placeholder: "Search entities by name or IRI", "aria-label": "Search entities" });
  const typeSel = select([{ value: "", label: "All types" }, ...types.map(t => ({ value: t, label: `${local(t)} (${status.types[t]})` }))], {});
  const depth = select(["1", "2", "3"], { value: "1" });
  const results = h("div", {}), detail = h("div", { class: "card muted" }, "Search for an entity, or pick one from the results."), graphBox = h("div", { class: "graph" });
  let current = ctx.arg || null, graph = null;
  root.append(h("h1", {}, "Explore"),
    h("div", { class: "card" }, h("div", { class: "inline-form" }, field("Search", q), field("Type", typeSel), field("Depth", depth), button("Search", { class: "primary", onClick: search })), results),
    h("div", { class: "split" }, detail, h("div", {}, graphBox, h("div", { class: "legend" }, types.map(t => h("span", { style: { "--c": colors.get(t) } }, local(t)))))));
  q.addEventListener("keydown", e => { if (e.key === "Enter") search(); });
  async function search() {
    results.replaceChildren(skeleton(3));
    try { const hits = await api.get(`/versions/${vid}/graph/search${qs({ q: q.value, type: typeSel.value, limit: 25 })}`);
      results.replaceChildren(hits.length ? table([{ label: "Entity", render: e => h("a", { href: "#", onClick: ev => { ev.preventDefault(); show(e.iri); } }, e.label) }, { label: "Types", render: e => e.types.map(t => badge(local(t), "neutral")) }, { label: "IRI", render: e => h("span", { class: "mono small" }, e.iri) }], hits) : h("p", { class: "muted" }, "No entities match.")); }
    catch (e) { errorToast(e); results.replaceChildren(); }
  }
  async function show(iri) {
    current = iri;
    detail.className = "card"; detail.replaceChildren(skeleton(5));
    try {
      const e = await api.get(`/versions/${vid}/graph/entity${qs({ iri })}`);
      const att = e.attachments || {};
      detail.replaceChildren(
        h("h2", {}, h("span", {}, e.label, " ", e.types.map(t => badge(local(t), "neutral"))), button("Expand", { class: "sm", onClick: () => expand(iri) })),
        h("p", { class: "mono small muted" }, e.iri),
        h("h3", {}, "Attributes"), e.attributes.length ? table([{ label: "Attribute", render: a => local(a.predicate) }, { label: "Value", render: a => h("span", {}, a.value, a.inferred ? badge("inferred", "neutral") : null) }], e.attributes) : h("p", { class: "muted small" }, "None."),
        h("h3", {}, "Relationships"), (e.outgoing.length || e.incoming.length) ? h("ul", { class: "list small" }, [...e.outgoing.map(r => h("li", {}, h("span", {}, `${local(r.predicate)} → `, h("a", { href: "#", onClick: ev => { ev.preventDefault(); show(r.target); } }, local(r.target)), r.inferred ? badge("inferred", "neutral") : null))),
          ...e.incoming.map(r => h("li", {}, h("span", {}, h("a", { href: "#", onClick: ev => { ev.preventDefault(); show(r.source); } }, local(r.source)), ` ${local(r.predicate)} → this`, r.inferred ? badge("inferred", "neutral") : null)))]) : h("p", { class: "muted small" }, "None."),
        att.virtual_attributes?.length ? h("div", {}, h("h3", {}, "Virtual attributes ", button("Compute", { class: "sm", onClick: () => virtual(iri) })), h("p", { class: "muted small" }, att.virtual_attributes.join(", "))) : null,
        att.actions?.length ? h("div", {}, h("h3", {}, "Actions"), h("div", { class: "row" }, att.actions.map(a => button(a, { class: "sm", onClick: () => action(iri, a) })))) : null,
        att.datasets?.length ? h("div", {}, h("h3", {}, "Datasets ", button("Show rows", { class: "sm", onClick: () => datasets(iri) })), h("p", { class: "muted small" }, att.datasets.join(", "))) : null,
        att.bridges?.length ? h("div", {}, h("h3", {}, "Bridges ", button("Resolve", { class: "sm", onClick: () => bridges(iri) })), h("p", { class: "muted small" }, att.bridges.join(", "))) : null);
      expand(iri);
    } catch (err) { errorToast(err); }
  }
  async function expand(iri) {
    try { const sub = await api.get(`/versions/${vid}/graph/neighbourhood${qs({ iri, depth: depth.value, limit: 150 })}`);
      const nodes = sub.nodes.map(n => ({ id: n.iri, label: n.label, color: colors.get(n.types[0]) || "#5a6470", size: n.iri === iri ? 10 : 6 }));
      const edges = sub.edges.map(e => ({ source: e.source, target: e.target, label: local(e.predicate) }));
      graph?.destroy?.(); graph = renderGraph(graphBox, { nodes, edges, selected: iri, onSelect: n => show(n.id) }); }
    catch (e) { errorToast(e); }
  }
  async function virtual(iri) { try { const v = await api.get(`/versions/${vid}/graph/entity/virtual${qs({ iri })}`); dialog("Virtual attributes", table([{ label: "Name", key: "k" }, { label: "Value", render: r => r.v ?? "—" }], Object.entries(v).map(([k, v]) => ({ k, v }))), { confirm: "Close", cancel: "Dismiss" }); } catch (e) { errorToast(e); } }
  async function action(iri, name) { try { const r = await api.post(`/versions/${vid}/graph/entity/actions/${encodeURIComponent(name)}${qs({ iri })}`);
    dialog(`Action: ${name}`, r.kind === "scalar" ? h("p", {}, h("strong", {}, r.value ?? "—")) : r.rows.length ? table(r.columns.map(c => ({ label: c, render: row => row[c] ?? "—" })), r.rows) : h("p", {}, "No rows."), { confirm: "Close", cancel: "Dismiss" }); } catch (e) { errorToast(e); } }
  async function datasets(iri) { try { const ds = await api.get(`/versions/${vid}/graph/entity/datasets${qs({ iri })}`);
    dialog("Datasets", h("div", {}, ds.map(d => h("div", {}, h("h3", {}, d.table, " ", h("span", { class: "muted small" }, d.description || "")), d.rows.length ? table(d.columns.map(c => ({ label: c, render: r => r[c] ?? "—" })), d.rows) : h("p", { class: "muted small" }, "No rows.")))), { confirm: "Close", cancel: "Dismiss" }); } catch (e) { errorToast(e); } }
  async function bridges(iri) { try { const b = await api.get(`/versions/${vid}/graph/entity/bridges${qs({ iri })}`);
    dialog("Bridges", table([{ label: "Domain", key: "domain" }, { label: "Entity", render: x => x.error ? badge(x.error, "error") : h("a", { href: `#/d/${encodeURIComponent(x.domain)}/explore/${encodeURIComponent(x.iri)}` }, x.label || local(x.iri)) }, { label: "Exists", render: x => x.exists ? badge("yes", "ok") : badge("no", "neutral") }], b), { confirm: "Close", cancel: "Dismiss" }); } catch (e) { errorToast(e); } }
  if (current) show(current); else search();
  return root;
}
