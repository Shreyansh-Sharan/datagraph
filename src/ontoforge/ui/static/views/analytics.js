// Analytics: communities, centralities, health, AI interpretation, run history.
import { api, local } from "../api.js";
import { h, button, input, select, field, dialog, toast, errorToast, badge, table, empty, kpis, fmtDate, fmtNum, markdown } from "../ui.js";

export async function analyticsTab(ctx) {
  const { version } = ctx; const vid = version.id;
  const status = await api.get(`/versions/${vid}/graph/status`);
  if (!status.triples) return empty("Nothing to analyse", "Build the graph first.", h("a", { class: "btn", href: `#/d/${encodeURIComponent(ctx.name)}/build` }, "Go to build"));
  let runs = await api.get(`/versions/${vid}/analytics/runs`);
  const root = h("div", {}), out = h("div", {}), history = h("div", {});
  const algo = select(["louvain", "label_propagation", "greedy_modularity"], {}); const res = input({ type: "number", value: 1.0, step: 0.1, min: 0.1 }); const persist = h("label", { class: "check" }, h("input", { type: "checkbox" }), "persist as triples");
  const topn = input({ type: "number", value: 20, min: 1, max: 200 });
  root.append(h("h1", {}, "Analytics"),
    h("div", { class: "grid" },
      h("div", { class: "card" }, h("h2", {}, "Communities"), h("div", { class: "inline-form" }, field("Algorithm", algo), field("Resolution", res), field("", persist), button("Detect", { class: "primary", onClick: communities }))),
      h("div", { class: "card" }, h("h2", {}, "Centralities"), h("div", { class: "inline-form" }, field("Top N", topn), button("Compute", { class: "primary", onClick: centralities }))),
      h("div", { class: "card" }, h("h2", {}, "Data-model health"), button("Check", { onClick: health }))),
    out, history);
  function renderHistory() {
    history.replaceChildren(h("div", { class: "card" }, h("h2", {}, "Run history"), runs.length ? table([
      { label: "When", render: r => fmtDate(r.started_at) }, { label: "Scope", key: "scope" }, { label: "Status", render: r => badge(r.status) }, { label: "Nodes", render: r => fmtNum(r.nodes) }, { label: "Edges", render: r => fmtNum(r.edges) },
      { label: "Components", render: r => fmtNum(r.components) }, { label: "Duration", render: r => r.duration_seconds != null ? `${r.duration_seconds.toFixed(2)}s` : "—" },
      { label: "", render: r => r.status === "succeeded" && r.scope === "centralities" ? button("Interpret", { class: "sm", onClick: () => interpret(r) }) : null }], runs) : h("p", { class: "muted" }, "No runs yet.")));
  }
  async function communities() {
    try { const r = await api.post(`/versions/${vid}/analytics/communities`, { algorithm: algo.value, resolution: Number(res.value), persist: persist.querySelector("input").checked });
      out.replaceChildren(h("div", { class: "card" }, h("h2", {}, `${r.count} communities (${r.algorithm})`), table([{ label: "#", key: "id" }, { label: "Label", key: "label" }, { label: "Size", key: "size" }, { label: "Members", render: c => h("span", { class: "small muted" }, c.members.slice(0, 8).map(local).join(", ") + (c.size > 8 ? " …" : "")) }], r.communities)));
      runs = await api.get(`/versions/${vid}/analytics/runs`); renderHistory(); } catch (e) { errorToast(e); }
  }
  async function centralities() {
    try { const r = await api.post(`/versions/${vid}/analytics/centralities`, { top_n: Number(topn.value) });
      const hist = (name, hgram) => h("div", {}, h("h3", {}, name, " ", h("span", { class: "muted small" }, `median ${fmt(hgram.median)} · p90 ${fmt(hgram.p90)}`)), h("div", { class: "hist", role: "img", "aria-label": `${name} distribution` }, hgram.bins.map(b => h("i", { style: { height: `${Math.max(1, b / Math.max(...hgram.bins, 1) * 100)}%` }, title: String(b) }))));
      out.replaceChildren(h("div", { class: "card" }, h("h2", {}, "Centralities ", r.estimated.length ? badge(`estimated: ${r.estimated.join(", ")}`, "warning") : null),
        kpis([["Nodes", fmtNum(r.kpis.nodes)], ["Edges", fmtNum(r.kpis.edges)], ["Components", r.kpis.components], ["Avg degree", r.kpis.avg_degree], ["Density", r.kpis.density], ["Elapsed", `${r.kpis.elapsed_seconds}s`]]),
        h("div", { class: "grid" }, Object.entries(r.histograms).map(([k, v]) => hist(k, v))),
        h("h3", {}, "Top entities by PageRank"), table([{ label: "Entity", render: t => h("a", { href: `#/d/${encodeURIComponent(ctx.name)}/explore/${encodeURIComponent(t.iri)}` }, t.label) }, ...["pagerank", "degree", "betweenness", "closeness", "clustering"].map(m => ({ label: m, render: t => h("div", { class: "bar" }, h("span", {}, ""), h("div", {}, h("i", { style: { width: `${Math.min(100, t[m] / (r.top[0][m] || 1) * 100)}%` } })), h("span", { class: "small" }, fmt(t[m]))) }))], r.top),
        button("Interpret with AI", { onClick: () => interpret({ id: r.run_id }) })));
      runs = await api.get(`/versions/${vid}/analytics/runs`); renderHistory(); } catch (e) { errorToast(e); }
  }
  async function health() {
    try { const rows = await api.get(`/versions/${vid}/analytics/health`);
      out.replaceChildren(h("div", { class: "card" }, h("h2", {}, "Data-model health"), table([{ label: "Type", render: r => local(r.entity_type) }, { label: "Instances", render: r => fmtNum(r.instances) }, { label: "Relationship predicates", key: "relationship_predicates" }, { label: "Flag", render: r => r.flag ? badge(r.flag, "warning") : badge("ok", "ok") }, { label: "Recommendation", render: r => r.recommendation || "—" }], rows))); }
    catch (e) { errorToast(e); }
  }
  async function interpret(run) {
    const comment = h("label", { class: "check" }, h("input", { type: "checkbox", checked: true }), "post as a comment");
    dialog("AI interpretation", h("div", {}, h("p", {}, "Ask the model to explain this run in business terms."), comment), { confirm: "Interpret", onConfirm: async () => {
      const r = await api.post(`/analytics/runs/${run.id}/interpret?comment=${comment.querySelector("input").checked}`);
      dialog("AI insights", h("div", {}, markdown(r.key_findings), h("h3", {}, "Notable entities"), h("ul", {}, r.notable_entities.map(e => h("li", {}, h("strong", {}, e.label), ": ", e.reason))), h("h3", {}, "Recommendations"), h("ul", {}, r.recommendations.map(x => h("li", {}, x)))), { confirm: "Close", cancel: "Dismiss" });
    }});
  }
  const fmt = (x) => x == null ? "—" : Number(x).toFixed(4);
  renderHistory();
  return root;
}
