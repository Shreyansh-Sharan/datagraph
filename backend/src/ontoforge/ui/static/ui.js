// Small DOM helpers and shared widgets. No framework: h() builds elements, views return elements.
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  append(el, children);
  return el;
}
export function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
export const clear = (el) => { el.replaceChildren(); return el; };
export const fmtDate = (s) => s ? new Date(s).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—";
export const fmtNum = (n) => n === null || n === undefined ? "—" : Number(n).toLocaleString();
export const pct = (x) => `${Math.round((x || 0) * 100)}%`;

export function toast(message, kind = "info", ms = 4500) {
  const box = document.getElementById("toasts");
  const t = h("div", { class: `toast ${kind}`, role: kind === "error" ? "alert" : "status" }, message);
  box.append(t);
  setTimeout(() => t.remove(), ms);
  return t;
}
export const errorToast = (e) => toast(e?.detail || e?.message || String(e), "error", 7000);

export function badge(text, kind) {
  return h("span", { class: `badge ${kind || String(text).toLowerCase().replace(/[^a-z_]/g, "")}` }, String(text).replace(/_/g, " "));
}

export function table(columns, rows, opts = {}) {
  const thead = h("thead", {}, h("tr", {}, columns.map(c => h("th", { scope: "col" }, c.label ?? c.key))));
  const tbody = h("tbody", {}, rows.map(r => h("tr", { onClick: opts.onRow ? () => opts.onRow(r) : null, style: opts.onRow ? { cursor: "pointer" } : null },
    columns.map(c => h("td", { class: c.class }, c.render ? c.render(r) : r[c.key] ?? "—")))));
  return h("div", { class: "table-wrap" }, h("table", {}, opts.caption ? h("caption", { class: "muted small" }, opts.caption) : null, thead, tbody));
}

export function empty(title, text, action) {
  return h("div", { class: "empty", role: "status" }, h("h3", {}, title), text ? h("p", {}, text) : null, action || null);
}
export function skeleton(n = 3) { return h("div", { "aria-busy": "true", "aria-label": "Loading" }, Array.from({ length: n }, () => h("div", { class: "skeleton" }))); }

export function field(label, input, hint) {
  const id = input.id || (input.id = `f_${Math.random().toString(36).slice(2, 8)}`);
  return h("div", { class: "field" }, h("label", { for: id }, label), input, hint ? h("div", { class: "muted small" }, hint) : null);
}
export const input = (attrs = {}) => h("input", { type: "text", ...attrs });
export const select = (options, attrs = {}) => h("select", attrs, options.map(o => typeof o === "string"
  ? h("option", { value: o, selected: attrs.value === o }, o)
  : h("option", { value: o.value, selected: attrs.value === o.value }, o.label)));
export const textarea = (attrs = {}) => h("textarea", attrs);
export const button = (label, attrs = {}) => h("button", { type: "button", ...attrs }, label);

export function dialog(title, body, { confirm = "Save", cancel = "Cancel", onConfirm, danger = false } = {}) {
  const d = h("dialog", { "aria-labelledby": "dlg-title" });
  const ok = button(confirm, { class: danger ? "danger" : "primary" });
  const no = button(cancel, {});
  d.append(h("h2", { id: "dlg-title" }, title), body, h("div", { class: "dialog-actions" }, no, ok));
  no.addEventListener("click", () => d.close());
  ok.addEventListener("click", async () => {
    ok.disabled = true;
    try { if (!onConfirm || (await onConfirm()) !== false) d.close(); }
    catch (e) { errorToast(e); }
    finally { ok.disabled = false; }
  });
  d.addEventListener("close", () => d.remove());
  document.body.append(d);
  d.showModal();
  return d;
}
export const confirmDialog = (title, text, onConfirm, opts = {}) => dialog(title, h("p", {}, text), { confirm: opts.confirm || "Confirm", onConfirm, danger: opts.danger });

export function tabs(items, active, onSelect) {
  return h("div", { class: "tabs", role: "tablist" }, items.map(t => h("button", {
    role: "tab", "aria-selected": String(t.id === active), onClick: () => onSelect(t.id) }, t.label)));
}

export function kpis(items) {
  return h("div", { class: "kpis" }, items.map(([l, v]) => h("div", { class: "kpi" }, h("div", { class: "v" }, v), h("div", { class: "l" }, l))));
}

export function progress(value) { return h("div", { class: "progress", role: "progressbar", "aria-valuenow": Math.round(value * 100), "aria-valuemin": 0, "aria-valuemax": 100 }, h("div", { style: { width: pct(value) } })); }

// Minimal markdown: paragraphs, **bold**, `code`, bullet lists. Content is escaped first.
export function markdown(text) {
  const esc = (s) => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`(.+?)`/g, "<code>$1</code>");
  const blocks = text.split(/\n{2,}/).map(b => {
    const lines = b.split("\n");
    if (lines.every(l => /^\s*[-*] /.test(l))) return `<ul>${lines.map(l => `<li>${inline(l.replace(/^\s*[-*] /, ""))}</li>`).join("")}</ul>`;
    return `<p>${lines.map(inline).join("<br>")}</p>`;
  });
  return h("div", { class: "md", html: blocks.join("") });
}
