// Triples grid: browse the raw triple store with filters and paging.
import { api, local, qs } from "../api.js";
import { h, button, input, select, field, badge, table, empty, fmtNum } from "../ui.js";

export async function triplesTab(ctx) {
  const { version } = ctx; const vid = version.id;
  const status = await api.get(`/versions/${vid}/graph/status`);
  if (!status.triples) return empty("No triples yet", "Build the knowledge graph first.");
  const preds = Object.keys(status.predicates).sort();
  const text = input({ type: "search", placeholder: "text in subject, predicate or object", "aria-label": "Filter text" });
  const pred = select([{ value: "", label: "Any predicate" }, ...preds.map(p => ({ value: p, label: `${local(p)} (${fmtNum(status.predicates[p])})` }))], { "aria-label": "Predicate" });
  const subj = input({ placeholder: "subject IRI", "aria-label": "Subject IRI" });
  const inferred = select([{ value: "", label: "asserted + inferred" }, { value: "false", label: "asserted only" }, { value: "true", label: "inferred only" }], { "aria-label": "Inferred filter" });
  const size = select(["50", "100", "250", "500"], { value: "100", "aria-label": "Rows per page" });
  let offset = 0;
  const grid = h("div", {}), pager = h("div", { class: "row" });
  const root = h("div", {}, h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Triples"), h("p", { class: "muted" }, `${fmtNum(status.triples)} triples · ${fmtNum(status.inferred)} inferred`)),
    h("form", { class: "searchbar", onSubmit: e => { e.preventDefault(); offset = 0; load(); } }, text, pred, subj, inferred, size, button("Apply", { class: "primary", type: "submit" }))), grid, pager);
  let sort = "subject", direction = "asc";
  const sortable = (key, label) => h("button", { type: "button", class: "th-sort" + (sort === key ? " active" : ""), "aria-sort": sort === key ? (direction === "asc" ? "ascending" : "descending") : "none",
    title: `Sort by ${label.toLowerCase()}`, onClick: () => { direction = sort === key && direction === "asc" ? "desc" : "asc"; sort = key; offset = 0; load(); } },
    label, h("span", { class: "arrow", "aria-hidden": "true" }, sort === key ? (direction === "asc" ? "↑" : "↓") : "↕"));
  async function load() {
    grid.replaceChildren(h("p", { class: "muted" }, "Loading…"));
    const page = await api.get(`/versions/${vid}/graph/triples${qs({ text: text.value, predicate: pred.value, subject: subj.value, inferred: inferred.value, limit: size.value, offset, sort, direction })}`);
    grid.replaceChildren(page.rows.length ? table([
      { label: sortable("subject", "Subject"), render: r => h("a", { href: `#/d/${encodeURIComponent(ctx.name)}/explore/${encodeURIComponent(r.subject)}`, class: "mono small" }, r.subject) },
      { label: sortable("predicate", "Predicate"), render: r => h("span", { class: "mono small", title: r.predicate }, local(r.predicate)) },
      { label: sortable("object", "Object"), render: r => r.object_type === "literal" ? h("span", {}, r.object, r.datatype ? h("span", { class: "muted small" }, ` ^^${local(r.datatype)}`) : null, r.lang ? h("span", { class: "muted small" }, ` @${r.lang}`) : null)
          : h("a", { href: `#/d/${encodeURIComponent(ctx.name)}/explore/${encodeURIComponent(r.object)}`, class: "mono small" }, r.object) },
      { label: sortable("inferred", "Inferred"), render: r => r.inferred ? badge("inferred", "neutral") : null },
    ], page.rows) : empty("No triples match", "Loosen the filters."));
    const pages = Math.max(1, Math.ceil(page.total / Number(size.value)));
    const cur = Math.floor(offset / Number(size.value)) + 1;
    pager.replaceChildren(button("‹ Previous", { class: "sm", disabled: offset === 0, onClick: () => { offset = Math.max(0, offset - Number(size.value)); load(); } }),
      h("span", { class: "muted small" }, `page ${cur} of ${pages} · ${fmtNum(page.total)} rows`),
      button("Next ›", { class: "sm", disabled: offset + Number(size.value) >= page.total, onClick: () => { offset += Number(size.value); load(); } }));
  }
  load();
  return root;
}
