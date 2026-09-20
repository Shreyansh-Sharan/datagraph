// Build: run/poll/cancel builds, see steps and drift, browse run history, reasoning actions.
import { api } from "../api.js";
import { h, button, dialog, toast, errorToast, badge, table, empty, kpis, fmtDate, fmtNum, progress, confirmDialog } from "../ui.js";

const STEPS = ["compile", "drift", "prepare", "publish", "load", "finalize"];

export async function buildTab(ctx) {
  const { version } = ctx; const vid = version.id;
  const root = h("div", {});
  let runs = await api.get(`/versions/${vid}/builds`);
  let status = await api.get(`/versions/${vid}/graph/status`);
  let timer = null;
  const head = h("div", { class: "page-head" }), stats = h("div", {}), body = h("div", {});
  root.append(head, stats, body);
  const canBuild = ["builder", "reviewer", "admin"].includes((await api.get("/me")).role);

  async function refresh() { runs = await api.get(`/versions/${vid}/builds`); status = await api.get(`/versions/${vid}/graph/status`); render(); }
  function render() {
    const running = runs.find(r => r.status === "running");
    head.replaceChildren(h("div", {}, h("h1", {}, "Build"), h("p", { class: "muted" }, "Compile the mapping to SQL, materialise the triples, then reason over them.")),
      h("div", { class: "actions" },
        canBuild ? button(running ? "Building…" : "Build now", { class: "primary", disabled: !!running || !version.has_mapping, onClick: startBuild }) : null,
        running && canBuild ? button("Cancel", { class: "danger", onClick: () => cancel(running) }) : null,
        canBuild && status.triples ? button("Infer (OWL RL)", { onClick: () => reason("infer") }) : null,
        canBuild && status.triples ? button("Run rules", { onClick: () => reason("rules") }) : null,
        canBuild && status.triples ? button("Validate", { onClick: () => reason("validate") }) : null));
    stats.replaceChildren(kpis([["Triples", fmtNum(status.triples)], ["Inferred", fmtNum(status.inferred)], ["Entity types", Object.keys(status.types || {}).length], ["Predicates", Object.keys(status.predicates || {}).length],
      ["Last build", status.last_build ? `${status.last_build.status} · ${fmtDate(status.last_build.finished_at || status.last_build.started_at)}` : "never"]]));
    body.replaceChildren();
    if (running) body.append(runCard(running, true));
    body.append(h("div", { class: "card" }, h("h2", {}, "Run history"), runs.length ? table([
      { label: "Started", render: r => fmtDate(r.started_at) }, { label: "Status", render: r => badge(r.status) }, { label: "Triples", render: r => fmtNum(r.triple_count) },
      { label: "Steps", render: r => h("span", { class: "small muted" }, (r.steps || []).map(s => `${s.name}${s.seconds != null ? ` ${s.seconds}s` : ""}`).join(" · ")) },
      { label: "By", render: r => r.actor || "—" }, { label: "", render: r => button("Details", { class: "sm", onClick: () => details(r) }) },
    ], runs) : empty("No builds yet", "Run a build once the mapping is complete.")));
    if (running && !timer) timer = setTimeout(async () => { timer = null; await refresh(); }, 1500);
    if (Object.keys(status.types || {}).length) body.append(h("div", { class: "card" }, h("h2", {}, "Entity types"), table([{ label: "Type", key: "t" }, { label: "Instances", render: r => fmtNum(r.n) }], Object.entries(status.types).map(([t, n]) => ({ t, n })))));
  }
  function runCard(r, live) {
    const done = (r.steps || []).filter(s => s.seconds != null).length;
    const drift = (r.steps || []).find(s => s.name === "drift")?.detail?.issues || [];
    return h("div", { class: "card", "aria-live": live ? "polite" : null }, h("h2", {}, h("span", {}, `Build ${live ? "in progress" : ""} `, badge(r.status))),
      progress(done / STEPS.length), h("p", { class: "small muted" }, STEPS.map(s => { const st = (r.steps || []).find(x => x.name === s); return `${st ? (st.error ? "✗" : st.seconds != null ? "✓" : "…") : "·"} ${s}`; }).join("   ")),
      drift.length ? h("div", { class: "notice warn" }, `${drift.length} schema drift issue(s) — see Mapping → Drift.`) : null,
      r.error ? h("div", { class: "notice error" }, r.error) : null);
  }
  function details(r) {
    dialog(`Build ${r.id.slice(0, 8)} · ${r.status}`, h("div", {}, runCard(r, false), h("pre", {}, JSON.stringify(r.steps, null, 2))), { confirm: "Close", cancel: "Dismiss" });
  }
  async function startBuild() { try { await api.post(`/versions/${vid}/builds`); toast("Build started", "ok"); await refresh(); } catch (e) { errorToast(e); } }
  async function cancel(r) { try { await api.post(`/builds/${r.id}/cancel`); toast("Cancelling…", "warn"); await refresh(); } catch (e) { errorToast(e); } }
  async function reason(kind) {
    try {
      if (kind === "infer") { const r = await api.post(`/versions/${vid}/reasoning/infer`); toast(`Inferred ${r.inferred} triples in ${r.seconds}s${r.inconsistent?.length ? ` · ${r.inconsistent.length} inconsistent entities` : ""}`, r.inconsistent?.length ? "warn" : "ok"); }
      else if (kind === "rules") { const r = await api.post(`/versions/${vid}/reasoning/rules`); toast(`Rules: ${r.materialised} triples materialised, ${r.violations.length} violations`, "ok"); }
      else { const r = await api.post(`/versions/${vid}/reasoning/quality`); dialog(`Data quality: ${r.conforms ? "conforms" : "violations found"}`, table([{ label: "Constraint", key: "name" }, { label: "Severity", render: x => badge(x.severity) }, { label: "Targets", key: "targets" }, { label: "Violations", key: "violations" }, { label: "Message", key: "message" }], r.results), { confirm: "Close", cancel: "Dismiss" }); }
      await refresh();
    } catch (e) { errorToast(e); }
  }
  render();
  return root;
}
