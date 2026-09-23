// Data quality: constraints (authored + derived), SHACL export/import, validation results.
import { api, local } from "../api.js";
import { h, button, input, select, field, dialog, toast, errorToast, badge, table, empty, kpis, confirmDialog } from "../ui.js";

const KINDS = ["min_count", "max_count", "datatype", "class", "pattern", "in", "min_inclusive", "max_inclusive", "min_exclusive", "max_exclusive", "unique", "node_kind", "require_label", "no_orphans"];

export async function qualityTab(ctx) {
  const { version } = ctx; const vid = version.id; const editable = version.status === "draft";
  const onto = version.has_ontology ? await api.get(`/versions/${vid}/ontology`) : { classes: [], datatype_properties: [], object_properties: [] };
  let cs = await api.get(`/versions/${vid}/quality`);
  let report = null;
  const root = h("div", {}), body = h("div", {}), results = h("div", {});
  root.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Data quality"), h("p", { class: "muted" }, "Constraints are validated with SQL over the graph. Ranges and cardinalities from the ontology are checked automatically.")),
    h("div", { class: "actions" }, editable ? button("Add constraint", { class: "primary", onClick: () => constraintDialog() }) : null,
      button("SHACL", { onClick: async () => { try { dialog("SHACL shapes", h("pre", {}, await api.text(`/versions/${vid}/quality/shacl`)), { confirm: "Close", cancel: "Dismiss" }); } catch (e) { errorToast(e); } } }),
      editable ? button("Import SHACL", { onClick: importShacl }) : null, button("Validate", { class: "primary", onClick: validate }))), body, results);
  function render() {
    body.replaceChildren(h("div", { class: "card" }, h("h2", {}, "Constraints"), cs.constraints.length ? table([
      { label: "Name", key: "name" }, { label: "Class", render: c => local(c.target_class) }, { label: "Property", render: c => c.property ? local(c.property) : "—" },
      { label: "Kind", render: c => badge(c.kind, "neutral") }, { label: "Value", render: c => c.value === null || c.value === undefined ? "—" : h("code", {}, typeof c.value === "string" ? local(c.value) : JSON.stringify(c.value)) },
      { label: "Severity", render: c => badge(c.severity) },
      { label: "", render: c => editable ? button("Remove", { class: "sm ghost", onClick: () => confirmDialog("Remove constraint", `Remove ${c.name}?`, () => save(cs.constraints.filter(x => x.name !== c.name)), { danger: true }) }) : null },
    ], cs.constraints) : h("p", { class: "muted" }, "No authored constraints. Ontology-derived checks still run.")));
  }
  async function save(constraints) { try { cs = await api.put(`/versions/${vid}/quality`, { constraints }); toast("Constraints saved", "ok"); render(); } catch (e) { errorToast(e); } }
  function constraintDialog() {
    const props = [...onto.datatype_properties, ...onto.object_properties];
    const name = input({ placeholder: "salary-floor" }), cls = select(onto.classes.map(c => ({ value: c.iri, label: local(c.iri) })), {});
    const prop = select([{ value: "", label: "— (entity-level)" }, ...props.map(p => ({ value: p.iri, label: local(p.iri) }))], {});
    const kind = select(KINDS, { value: "min_count" }), value = input({ value: "1" }), sev = select(["violation", "warning", "info"], {}), msg = input({ placeholder: "optional message" });
    dialog("New constraint", h("div", {}, h("div", { class: "form-row" }, field("Name", name), field("Class", cls)), h("div", { class: "form-row" }, field("Property", prop), field("Kind", kind)),
      h("div", { class: "form-row" }, field("Value", value, "number, IRI, regex, or JSON list for 'in'"), field("Severity", sev)), field("Message", msg)),
      { confirm: "Add", onConfirm: async () => {
        let v = value.value.trim(); if (["min_count", "max_count", "min_inclusive", "max_inclusive", "min_exclusive", "max_exclusive"].includes(kind.value)) v = Number(v);
        else if (kind.value === "in") v = JSON.parse(v); else if (["unique"].includes(kind.value)) v = true; else if (["require_label", "no_orphans"].includes(kind.value)) v = null;
        else if (kind.value === "datatype" && !v.includes("#")) v = `http://www.w3.org/2001/XMLSchema#${v}`;
        await save([...cs.constraints, { name: name.value.trim(), target_class: cls.value, property: prop.value || null, kind: kind.value, value: v, severity: sev.value, message: msg.value || null }]);
      }});
  }
  function importShacl() {
    const file = input({ type: "file", accept: ".ttl" });
    dialog("Import SHACL", field("Turtle file", file), { confirm: "Import", onConfirm: async () => { if (!file.files[0]) throw new Error("Choose a file"); cs = await api.post(`/versions/${vid}/quality/import-shacl`, { turtle: await file.files[0].text() }); toast("Constraints imported", "ok"); render(); } });
  }
  async function validate() {
    results.replaceChildren(h("p", { class: "muted" }, "Validating…"));
    try { report = await api.post(`/versions/${vid}/reasoning/quality`);
      results.replaceChildren(h("div", { class: "card" }, h("h2", {}, h("span", {}, "Results ", report.conforms ? badge("conforms", "ok") : badge("violations", "error"))),
        kpis([["Violations", report.summary.violation], ["Warnings", report.summary.warning], ["Info", report.summary.info]]),
        table([{ label: "Constraint", key: "name" }, { label: "Kind", render: r => badge(r.kind, "neutral") }, { label: "Severity", render: r => badge(r.severity) }, { label: "Targets", key: "targets" },
          { label: "Violations", render: r => r.violations ? h("strong", {}, r.violations) : "0" }, { label: "Pass", render: r => r.targets ? `${Math.round((1 - Math.min(1, r.violations / r.targets)) * 100)}%` : "—" },
          { label: "", render: r => r.samples.length ? button("Samples", { class: "sm", onClick: () => dialog(r.name, table([{ label: "Entity", render: s => h("span", { class: "mono small" }, s.focus) }, { label: "Value", render: s => s.value ?? "—" }, { label: "Message", key: "message" }], r.samples), { confirm: "Close", cancel: "Dismiss" }) }) : null }], report.results))); }
    catch (e) { errorToast(e); results.replaceChildren(); }
  }
  render();
  return root;
}
