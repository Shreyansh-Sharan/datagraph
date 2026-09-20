// Bootstrap: identity, hash router, shell (topbar + sidenav), view dispatch.
import { api, identity, loadAuthConfig, authConfig } from "./api.js";
import { h, clear, button, input, field, dialog, toast, errorToast, badge } from "./ui.js";
import { domainsView } from "./views/domains.js";
import { domainView, DOMAIN_TABS } from "./views/domain.js";
import { iconEl } from "./icons.js";
import { adminView } from "./views/admin.js";
import { tasksView } from "./views/tasks.js";

const routes = [
  { re: /^#\/?$/, view: () => domainsView() },
  { re: /^#\/domains$/, view: () => domainsView() },
  { re: /^#\/tasks$/, view: () => tasksView() },
  { re: /^#\/admin(?:\/(\w+))?$/, view: (m) => adminView(m[1] || "principals") },
  { re: /^#\/d\/([^/]+)(?:\/([^/]+))?(?:\/(.*))?$/, view: (m) => domainView(decodeURIComponent(m[1]), m[2] || "overview", m[3] ? decodeURIComponent(m[3]) : null) },
];

export const state = { me: null, domain: null, version: null, progress: null };

const THEME_KEY = "of.theme";
export function applyTheme(t) { const v = t || localStorage.getItem(THEME_KEY) || ""; if (v) document.documentElement.dataset.theme = v; else delete document.documentElement.dataset.theme; }
function toggleTheme() {
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  const cur = localStorage.getItem(THEME_KEY) || (dark ? "dark" : "light");
  const next = cur === "dark" ? "light" : "dark";
  localStorage.setItem(THEME_KEY, next); applyTheme(next); renderTopbar();
}

export async function whoami() {
  try { state.me = await api.get("/me"); } catch (e) { state.me = null; if (e.status !== 401) errorToast(e); }
  renderTopbar();
  return state.me;
}

function identityDialog() {
  const mode = authConfig.mode;
  const actor = input({ value: identity.actor, placeholder: "e.g. alice", autocomplete: "username" });
  const token = input({ value: identity.token, type: "password", placeholder: "of_…", autocomplete: "off" });
  const body = h("div", {},
    mode === "token"
      ? field("API key", token, "Issued by an admin under Admin → API keys. Stored in this browser only.")
      : field(`Identity (${authConfig.header})`, actor, `Header mode: the value is sent as ${authConfig.header}. Behind a reverse proxy the proxy sets it and this is ignored.`),
    h("p", { class: "muted small" }, `Unknown identities get the "${authConfig.default_role}" role.`));
  dialog("Sign in", body, { confirm: "Use identity", onConfirm: async () => {
    if (mode === "token") identity.token = token.value.trim(); else identity.actor = actor.value.trim();
    const me = await whoami();
    if (!me) { toast("Could not sign in with that identity", "error"); return false; }
    toast(`Signed in as ${me.name} (${me.role})`, "ok");
    route();
  }});
}

function renderTopbar() {
  const bar = clear(document.getElementById("topbar"));
  const crumbs = h("nav", { class: "crumbs", "aria-label": "Breadcrumb" }, h("a", { href: "#/domains" }, iconEl("overview"), "Domains"));
  if (state.domain) {
    const base = `#/d/${encodeURIComponent(state.domain.name)}`;
    crumbs.append(h("span", { class: "sep" }, "›"), h("a", { href: base, class: "crumb" }, iconEl("domain"), state.domain.name,
      state.version ? h("span", { class: "muted" }, ` v${state.version.version}`) : null));
    const p = state.progress || {};
    for (const [id, label, done] of [["ontology", "Ontology", p.ontology], ["mapping", "Mapping", p.mapping], ["build", "Graph", p.built]]) {
      crumbs.append(h("span", { class: "sep" }, "›"), h("a", { href: `${base}/${id}`, class: `crumb step ${done ? "done" : ""}` },
        h("span", { class: "tick", "aria-hidden": "true" }, done ? iconEl("check") : ""), label));
    }
    if (state.version) crumbs.append(badge(state.version.status));
  }
  const me = state.me;
  const dark = (localStorage.getItem(THEME_KEY) || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
  bar.append(
    h("a", { class: "brand", href: "#/domains" }, h("span", { class: "dot", "aria-hidden": "true" }), "ontoforge"),
    crumbs, h("div", { class: "spacer" }),
    h("a", { href: "#/tasks", class: "topnav" }, iconEl("tasks"), "My tasks"),
    me?.role === "admin" ? h("a", { href: "#/admin", class: "topnav" }, iconEl("shield"), "Admin") : null,
    button(iconEl(dark ? "sun" : "moon"), { class: "sm ghost", title: dark ? "Switch to light theme" : "Switch to dark theme", "aria-label": "Toggle theme", onClick: toggleTheme }),
    h("div", { class: "identity" },
      me ? h("span", { class: "chip", title: `role: ${me.role}` }, me.name, h("span", { class: "muted" }, me.role)) : h("span", { class: "chip" }, "not signed in"),
      button(me ? "Switch" : "Sign in", { class: "sm", onClick: identityDialog })));
}

export function renderSidenav(items, activeId, base, versions = null) {
  const nav = clear(document.getElementById("sidenav"));
  if (!items) return;
  if (versions?.length) {
    const key = `of.version.${state.domain?.name}`;
    const sel = h("select", { "aria-label": "Version", onChange: (e) => { localStorage.setItem(key, e.target.value); route(); } },
      versions.map(v => h("option", { value: v.version, selected: state.version?.version === v.version }, `v${v.version} · ${v.status.replace("_", " ")}`)));
    nav.append(h("div", { class: "version-pick" }, sel));
  }
  let group = null;
  for (const it of items) {
    if (it.group && it.group !== group) { group = it.group; nav.append(h("div", { class: "group" }, group)); }
    nav.append(h("a", { href: `${base}/${it.id}`, "aria-current": it.id === activeId ? "page" : null }, h("span", { class: "nav-label" }, iconEl(it.icon || it.id), it.label), it.count !== undefined ? h("span", { class: "chip" }, it.count) : null));
  }
}

let current = 0;
export async function route() {
  const hash = location.hash || "#/domains";
  const mine = ++current;
  const main = document.getElementById("main");
  for (const r of routes) {
    const m = hash.match(r.re);
    if (!m) continue;
    if (!hash.startsWith("#/d/")) { state.domain = state.version = null; renderSidenav(null); renderTopbar(); }
    try {
      const el = await r.view(m);
      if (mine !== current) return;
      clear(main).append(el);
      renderTopbar();
    } catch (e) {
      if (mine !== current) return;
      clear(main).append(h("div", { class: "notice error", role: "alert" }, e.detail || e.message || String(e)),
        e.status === 401 ? h("p", {}, button("Sign in", { class: "primary", onClick: identityDialog })) : null);
    }
    return;
  }
  clear(main).append(h("div", { class: "empty" }, h("h3", {}, "Not found"), h("a", { href: "#/domains" }, "Back to domains")));
}

window.addEventListener("hashchange", route);
(async () => {
  applyTheme();
  await loadAuthConfig();
  await whoami();
  if (!state.me) identityDialog();
  route();
})();
