// Domain shell: resolves the working version, renders the side navigation, dispatches tabs.
import { api } from "../api.js";
import { h, badge, button, dialog, field, input, select, textarea, toast, errorToast, fmtDate, confirmDialog, markdown, empty } from "../ui.js";
import { state, renderSidenav, route } from "../app.js";
import { ontologyTab } from "./ontology.js";
import { mappingTab } from "./mapping.js";
import { metadataTab } from "./metadata.js";
import { buildTab } from "./build.js";
import { exploreTab } from "./explore.js";
import { rulesTab } from "./rules.js";
import { qualityTab } from "./quality.js";
import { analyticsTab } from "./analytics.js";
import { settingsTab } from "./settings.js";
import { triplesTab } from "./triples.js";

export const DOMAIN_TABS = [
  { id: "overview", label: "Overview", group: "Domain", icon: "info" },
  { id: "metadata", label: "Metadata", group: "Design", icon: "table" },
  { id: "ontology", label: "Ontology", group: "Design", icon: "ontology" },
  { id: "mapping", label: "Mapping", group: "Design", icon: "mapping" },
  { id: "rules", label: "Rules", group: "Design", icon: "rules" },
  { id: "quality", label: "Data quality", group: "Design", icon: "quality" },
  { id: "build", label: "Build", group: "Knowledge graph", icon: "build" },
  { id: "explore", label: "Explore", group: "Knowledge graph", icon: "explore" },
  { id: "triples", label: "Triples", group: "Knowledge graph", icon: "triples" },
  { id: "analytics", label: "Analytics", group: "Knowledge graph", icon: "analytics" },
  { id: "settings", label: "Settings", group: "Domain", icon: "settings" },
];

export async function domainView(name, tab, arg) {
  const domain = await api.get(`/domains/${encodeURIComponent(name)}`);
  const versions = await api.get(`/domains/${encodeURIComponent(name)}/versions`);
  const wanted = localStorage.getItem(`of.version.${name}`);
  const version = versions.find(v => String(v.version) === wanted) || versions.find(v => v.status === "draft") || versions[0] || null;
  state.domain = domain; state.version = version;
  state.progress = version ? { ontology: version.has_ontology, mapping: version.has_mapping, built: false } : null;
  if (version) api.get(`/versions/${version.id}/builds`).then(runs => { state.progress.built = runs.some(r => r.status === "succeeded"); }).catch(() => {});
  renderSidenav(DOMAIN_TABS, tab, `#/d/${encodeURIComponent(name)}`, versions);
  const reload = () => { const target = `#/d/${encodeURIComponent(name)}/${tab}`; if (location.hash === target) return route(); location.hash = target; return Promise.resolve(); };
  const ctx = { domain, version, versions, name, reload, arg };
  if (tab !== "overview" && tab !== "settings" && !version) return needVersion(ctx);
  const views = { overview: overviewTab, ontology: ontologyTab, mapping: mappingTab, metadata: metadataTab, build: buildTab,
    explore: exploreTab, triples: triplesTab, rules: rulesTab, quality: qualityTab, analytics: analyticsTab, settings: settingsTab };
  const view = views[tab] || overviewTab;
  return view(ctx);
}

function needVersion(ctx) {
  return empty("No version yet", "Create a draft version to start designing this domain.",
    button("Create draft", { class: "primary", onClick: () => createDraft(ctx) }));
}

export async function createDraft(ctx) {
  try { await api.post(`/domains/${encodeURIComponent(ctx.name)}/versions`); toast("Draft created", "ok"); location.hash = `#/d/${encodeURIComponent(ctx.name)}/overview`; }
  catch (e) { errorToast(e); }
}

async function overviewTab(ctx) {
  const { domain, versions, name } = ctx;
  const root = h("div", {});
  root.append(h("div", { class: "page-head" },
    h("div", {}, h("h1", {}, domain.name), h("p", { class: "muted" }, domain.description || "No description"),
      h("div", { class: "row small muted" }, h("span", { class: "mono" }, domain.base_iri), h("span", {}, `quorum ${domain.review_quorum}`),
        domain.active_version_id ? badge("active version pinned", "ok") : null)),
    h("div", { class: "actions" },
      versions.some(v => v.status === "draft") ? null : button("New draft", { class: "primary", onClick: () => createDraft(ctx) }),
      button("Export bundle", { onClick: () => exportBundle(name) }))));

  const list = h("div", { class: "stack" });
  for (const v of versions) list.append(await versionCard(ctx, v));
  root.append(h("h2", {}, "Versions"), versions.length ? list : empty("No versions", "Create a draft to begin."));
  return root;
}

async function versionCard(ctx, v) {
  const { domain, name } = ctx;
  const me = state.me || { role: "viewer" };
  const canBuild = ["builder", "reviewer", "admin"].includes(me.role);
  const canReview = ["reviewer", "admin"].includes(me.role);
  const status = v.status;
  const actions = [];
  const act = (label, fn, cls) => actions.push(button(label, { class: cls || "", onClick: async () => { try { await fn(); ctx.reload(); } catch (e) { errorToast(e); } } }));
  if (status === "draft" && canBuild) act("Submit for review", () => transition(v, "in_review"), "primary");
  if (status === "in_review" && canReview) { act("Approve", () => review(v, true)); act("Request changes", () => review(v, false)); act("Publish", () => transition(v, "published"), "primary"); }
  if (status === "in_review" && canBuild) act("Back to draft", () => transition(v, "draft"));
  if (status === "published" && canReview && domain.active_version_id !== v.id) act("Set active", () => api.post(`/domains/${encodeURIComponent(name)}/active`, { version_id: v.id }));
  if (status === "published" && me.role === "admin") act("Archive", () => confirmAsync("Archive version", `Archive v${v.version}? It will no longer be served.`, () => transition(v, "archived")), "danger");
  const reviews = status !== "draft" ? await api.get(`/versions/${v.id}/reviews`).catch(() => []) : [];
  const comments = await api.get(`/versions/${v.id}/comments`).catch(() => []);
  const audit = await api.get(`/versions/${v.id}/audit`).catch(() => []);
  const build = await api.get(`/versions/${v.id}/builds`).catch(() => []);
  const last = build[0];
  const facts = h("div", { class: "row small muted" },
    v.has_ontology ? badge("ontology", "ok") : badge("no ontology", "neutral"),
    v.has_mapping ? badge("mapping", "ok") : badge("no mapping", "neutral"),
    v.rule_count ? badge(`${v.rule_count} rules`, "neutral") : null, v.constraint_count ? badge(`${v.constraint_count} constraints`, "neutral") : null,
    last ? badge(`build ${last.status}${last.triple_count ? ` · ${last.triple_count} triples` : ""}`, last.status) : badge("not built", "neutral"),
    v.editor ? h("span", {}, `editing: ${v.editor}`) : null, domain.active_version_id === v.id ? badge("active", "ok") : null);
  const card = h("div", { class: "card" },
    h("h2", {}, h("span", {}, `Version ${v.version} `, badge(status)), h("span", { class: "row" }, actions, h("a", { class: "btn", href: `#/d/${encodeURIComponent(name)}/ontology`, onClick: () => localStorage.setItem(`of.version.${name}`, String(v.version)) }, "Open"))),
    facts,
    reviews.length ? h("div", { class: "small" }, h("strong", {}, "Reviews: "), reviews.map(r => h("span", { class: "chip" }, `${r.reviewer}: ${r.approved ? "approved" : "changes requested"}${r.comment ? " — " + r.comment : ""}`))) : null,
    h("details", {}, h("summary", { class: "small muted" }, `Discussion (${comments.length}) · Audit (${audit.length})`),
      h("div", { class: "split" },
        h("div", {}, h("h3", {}, "Discussion"), comments.length ? comments.map(c => h("div", { class: "comment" }, h("div", { class: "meta" }, `${c.author} · ${fmtDate(c.created_at)}`), markdown(c.body))) : h("p", { class: "muted small" }, "No comments."),
          commentForm(v, ctx)),
        h("div", {}, h("h3", {}, "Audit trail"), h("ul", { class: "list small" }, audit.slice(-25).reverse().map(a => h("li", {}, h("span", {}, h("strong", {}, a.action), a.actor ? ` · ${a.actor}` : ""), h("span", { class: "muted" }, fmtDate(a.created_at)))))))));
  return card;
}

function commentForm(v, ctx) {
  const ta = textarea({ placeholder: "Write a comment (markdown supported)", rows: 3 });
  return h("div", { class: "stack" }, ta, button("Post comment", { class: "sm", onClick: async () => {
    if (!ta.value.trim()) return;
    try { await api.post(`/versions/${v.id}/comments`, { body: ta.value }); toast("Comment posted", "ok"); ctx.reload(); } catch (e) { errorToast(e); }
  }}));
}

const transition = (v, to) => api.post(`/versions/${v.id}/transition`, { to });
function review(v, approved) {
  return new Promise((resolve, reject) => {
    const c = textarea({ placeholder: approved ? "Looks good" : "What needs to change?" });
    dialog(approved ? "Approve version" : "Request changes", field("Comment", c), { confirm: approved ? "Approve" : "Request changes",
      onConfirm: async () => { await api.post(`/versions/${v.id}/reviews`, { approved, comment: c.value || null }); resolve(); } });
  });
}
const confirmAsync = (title, text, fn) => new Promise(resolve => confirmDialog(title, text, async () => { await fn(); resolve(); }, { danger: true }));

async function exportBundle(name) {
  const which = select(["active", "latest", "all"], { value: "all" });
  dialog("Export bundle", field("Versions", which), { confirm: "Download", onConfirm: async () => {
    const bundle = await api.get(`/domains/${encodeURIComponent(name)}/export?versions=${which.value}`);
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
    const a = h("a", { href: URL.createObjectURL(blob), download: `${name}-bundle.json` });
    document.body.append(a); a.click(); a.remove();
  }});
}
