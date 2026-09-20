import { api } from "../api.js";
import { h, table, badge, button, input, field, dialog, empty, skeleton, toast, errorToast, fmtDate } from "../ui.js";

export async function domainsView() {
  const root = h("div", {});
  const head = h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Domains"), h("p", { class: "muted" }, "A domain is one knowledge graph: an ontology, a mapping onto tables, and the graph built from them.")),
    h("div", { class: "actions" }, button("Import bundle", { onClick: importDialog }), button("New domain", { class: "primary", onClick: () => createDialog(load) })));
  const body = h("div", {}, skeleton(4));
  root.append(head, body);
  async function load() {
    const domains = await api.get("/domains");
    body.replaceChildren(domains.length ? table([
      { label: "Name", render: d => h("a", { href: `#/d/${encodeURIComponent(d.name)}` }, h("strong", {}, d.name)) },
      { label: "Description", render: d => d.description || h("span", { class: "muted" }, "—") },
      { label: "Base IRI", render: d => h("span", { class: "mono" }, d.base_iri) },
      { label: "MCP", render: d => d.mcp_policy?.exposed === false ? badge("hidden", "neutral") : badge("exposed", "ok") },
      { label: "Created", render: d => fmtDate(d.created_at) },
    ], domains) : empty("No domains yet", "Create one, or import a bundle exported from another environment.",
      button("New domain", { class: "primary", onClick: () => createDialog(load) })));
  }
  load().catch(e => body.replaceChildren(h("div", { class: "notice error" }, e.detail || e.message)));
  return root;
}

function createDialog(after) {
  const name = input({ placeholder: "hr", pattern: "[A-Za-z0-9_-]+", required: true });
  const desc = input({ placeholder: "People and departments" });
  const base = input({ value: `http://${location.hostname || "example.org"}/`, placeholder: "http://example.org/hr/" });
  const quorum = input({ type: "number", value: 1, min: 0 });
  dialog("New domain", h("div", {}, field("Name", name, "Letters, digits, - and _ only."), field("Description", desc),
    field("Base IRI", base, "Entity IRIs are minted under this prefix."), field("Review quorum", quorum, "Approvals needed before publishing.")),
    { confirm: "Create", onConfirm: async () => {
      const d = await api.post("/domains", { name: name.value.trim(), description: desc.value || null, base_iri: base.value.trim(), review_quorum: Number(quorum.value) });
      toast(`Domain ${d.name} created`, "ok");
      location.hash = `#/d/${encodeURIComponent(d.name)}`;
      after?.();
    }});
}

function importDialog() {
  const file = input({ type: "file", accept: "application/json,.json" });
  const name = input({ placeholder: "(keep the bundle's name)" });
  const conflict = h("select", {}, ["fail", "skip", "overwrite", "rename"].map(o => h("option", { value: o }, o)));
  dialog("Import bundle", h("div", {}, field("Bundle file (.json)", file), field("Import as", name), field("If the domain exists", conflict)),
    { confirm: "Import", onConfirm: async () => {
      if (!file.files[0]) { toast("Choose a bundle file", "warn"); return false; }
      const bundle = JSON.parse(await file.files[0].text());
      if (name.value.trim()) bundle.name = name.value.trim();
      const r = await api.post(`/domains/import?on_conflict=${conflict.value}`, bundle);
      toast(`Imported ${r.imported.length} version(s) into ${r.domain}` + (r.skipped.length ? `, skipped ${r.skipped.length}` : ""), "ok");
      location.hash = `#/d/${encodeURIComponent(r.domain)}`;
    }});
}
