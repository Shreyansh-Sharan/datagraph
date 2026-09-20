// Ontology editor: class list + detail form, properties, restrictions, checks, import, AI assist, graph.
import { api, local, qs } from "../api.js";
import { h, button, input, select, textarea, field, dialog, toast, errorToast, badge, table, empty, tabs, skeleton, confirmDialog } from "../ui.js";
import { renderGraph, palette } from "../graph.js";

const XSD = "http://www.w3.org/2001/XMLSchema#";
const XSD_TYPES = ["string", "integer", "decimal", "double", "boolean", "date", "dateTime", "time"];
const CHARACTERISTICS = ["functional", "inverse_functional", "transitive", "symmetric", "asymmetric", "reflexive", "irreflexive"];

export async function ontologyTab(ctx) {
  const { version } = ctx;
  const vid = version.id;
  const root = h("div", {});
  let onto = version.has_ontology ? await api.get(`/versions/${vid}/ontology`) : null;
  let selected = ctx.arg || null;
  let mode = "list";
  const editable = version.status === "draft";

  const head = h("div", { class: "page-head" });
  const body = h("div", {});
  root.append(head, body);

  const render = () => {
    head.replaceChildren(
      h("div", {}, h("h1", {}, "Ontology"), h("p", { class: "muted" }, onto ? `${onto.label || onto.iri} · ${onto.classes.length} classes · ${onto.datatype_properties.length} attributes · ${onto.object_properties.length} relationships` : "No ontology yet.")),
      h("div", { class: "actions" },
        editable ? button("Draft from tables", { onClick: autodraft }) : null,
        editable ? button("Draft with AI", { onClick: aiDraft }) : null,
        editable ? button("Import", { onClick: importDialog }) : null,
        onto ? button("Checks", { onClick: showChecks }) : null,
        onto ? button("Turtle", { onClick: showTurtle }) : null,
        onto && editable ? button("AI assist", { onClick: aiAssist }) : null,
        onto && editable ? button("Save", { class: "primary", onClick: save }) : null));
    body.replaceChildren();
    if (!onto) { body.append(empty("Start the ontology", "Draft it from your tables, ask the AI, import an OWL file, or add the first class by hand.",
      editable ? button("Add class", { class: "primary", onClick: () => { onto = { iri: ctx.domain.base_iri.replace(/\/$/, ""), label: ctx.domain.name, description: null, classes: [], object_properties: [], datatype_properties: [] }; addClass(); } }) : null)); return; }
    body.append(tabs([{ id: "list", label: "Classes" }, { id: "graph", label: "Graph" }], mode, m => { mode = m; render(); }));
    body.append(mode === "graph" ? graphView() : listView());
  };

  function listView() {
    const search = input({ placeholder: "Filter classes", "aria-label": "Filter classes" });
    const list = h("ul", { class: "list" });
    const refill = () => {
      const q = search.value.toLowerCase();
      list.replaceChildren(...onto.classes.filter(c => !q || (c.label || local(c.iri)).toLowerCase().includes(q)).sort((a, b) => local(a.iri).localeCompare(local(b.iri)))
        .map(c => h("li", { class: c.iri === selected ? "selected" : "" },
          h("a", { href: "#", onClick: (e) => { e.preventDefault(); selected = c.iri; render(); } }, c.label || local(c.iri),
            c.parents?.length ? h("span", { class: "muted small" }, ` ⊂ ${c.parents.map(local).join(", ")}`) : null),
          h("span", { class: "muted small" }, `${propsOf(c.iri).length} props`))));
      if (!list.children.length) list.append(h("li", { class: "muted" }, "No classes match."));
    };
    search.addEventListener("input", refill); refill();
    const left = h("div", { class: "card" }, h("h2", {}, "Classes", editable ? button("Add class", { class: "sm primary", onClick: addClass }) : null), search, list);
    const cls = onto.classes.find(c => c.iri === selected);
    return h("div", { class: "split" }, left, cls ? classDetail(cls) : h("div", { class: "card muted" }, "Select a class to see its properties."));
  }

  function propsOf(iri) {
    const anc = ancestors(iri);
    return [...onto.datatype_properties.map(p => ({ ...p, kind: "attribute" })), ...onto.object_properties.map(p => ({ ...p, kind: "relationship" }))]
      .filter(p => p.domain === iri || p.domain === null || anc.includes(p.domain));
  }
  function ancestors(iri) { const out = []; const stack = [...(onto.classes.find(c => c.iri === iri)?.parents || [])]; while (stack.length) { const p = stack.shift(); if (out.includes(p)) continue; out.push(p); stack.push(...(onto.classes.find(c => c.iri === p)?.parents || [])); } return out; }

  function classDetail(cls) {
    const label = input({ value: cls.label || "", disabled: !editable });
    const desc = textarea({ value: cls.description || "", rows: 2, disabled: !editable });
    const parents = h("select", { multiple: true, size: 4, disabled: !editable }, onto.classes.filter(c => c.iri !== cls.iri).map(c => h("option", { value: c.iri, selected: cls.parents?.includes(c.iri) }, local(c.iri))));
    const apply = () => { cls.label = label.value; cls.description = desc.value || null; cls.parents = [...parents.selectedOptions].map(o => o.value); };
    [label, desc, parents].forEach(el => el.addEventListener("change", apply));
    const props = propsOf(cls.iri);
    const propTable = table([
      { label: "Property", render: p => h("span", {}, h("strong", {}, p.label || local(p.iri)), p.domain !== cls.iri ? h("span", { class: "muted small" }, p.domain ? ` (from ${local(p.domain)})` : " (global)") : null) },
      { label: "Kind", render: p => badge(p.kind, "neutral") },
      { label: "Range", render: p => p.range ? local(p.range) : "—" },
      { label: "Traits", render: p => h("span", { class: "small muted" }, [p.functional ? "functional" : null, ...(p.characteristics || [])].filter(Boolean).join(", ") || "—") },
      { label: "", render: p => editable && p.domain === cls.iri ? h("span", { class: "row" }, button("Edit", { class: "sm", onClick: () => propertyDialog(p, cls.iri) }), button("Remove", { class: "sm ghost", onClick: () => removeProperty(p) })) : null },
    ], props);
    const restr = h("div", {}, h("h3", {}, "Restrictions", editable ? button("Add", { class: "sm", onClick: () => restrictionDialog(cls) }) : null),
      (cls.restrictions || []).length ? h("ul", { class: "list small" }, cls.restrictions.map((r, i) => h("li", {}, h("span", {}, `${local(r.property)} ${r.kind} ${typeof r.value === "string" ? local(r.value) : r.value}`), editable ? button("×", { class: "sm ghost", "aria-label": "Remove restriction", onClick: () => { cls.restrictions.splice(i, 1); render(); } }) : null))) : h("p", { class: "muted small" }, "None."));
    return h("div", { class: "card" },
      h("h2", {}, h("span", {}, local(cls.iri)), editable ? button("Delete class", { class: "sm danger", onClick: () => deleteClass(cls) }) : null),
      h("div", { class: "muted small mono" }, cls.iri),
      h("div", { class: "form-row" }, field("Label", label), field("Parents", parents)), field("Description", desc),
      h("h3", {}, "Properties", editable ? h("span", { class: "row" }, button("Add attribute", { class: "sm", onClick: () => propertyDialog(null, cls.iri, "attribute") }), button("Add relationship", { class: "sm", onClick: () => propertyDialog(null, cls.iri, "relationship") })) : null),
      props.length ? propTable : h("p", { class: "muted small" }, "No properties yet."),
      restr,
      (cls.disjoint_with?.length || cls.equivalent_to?.length) ? h("p", { class: "small muted" }, cls.disjoint_with?.length ? `Disjoint with: ${cls.disjoint_with.map(local).join(", ")}. ` : "", cls.equivalent_to?.length ? `Equivalent to: ${cls.equivalent_to.map(local).join(", ")}.` : "") : null);
  }

  function mint(name, capitalize) {
    const words = name.match(/[A-Za-z0-9]+/g) || []; if (!words.length) throw new Error("Name needs letters or digits");
    let n = words.map(w => w[0].toUpperCase() + w.slice(1)).join(""); if (!capitalize) n = n[0].toLowerCase() + n.slice(1);
    return `${onto.iri}#${n}`;
  }
  function addClass() {
    const name = input({ placeholder: "Cost centre" }), desc = input({});
    dialog("New class", h("div", {}, field("Name", name), field("Description", desc)), { confirm: "Add", onConfirm: () => {
      const iri = mint(name.value, true);
      if (onto.classes.some(c => c.iri === iri)) throw new Error("A class with that name exists");
      onto.classes.push({ iri, label: name.value.trim(), description: desc.value || null, parents: [], equivalent_to: [], disjoint_with: [], restrictions: [] });
      selected = iri; render();
    }});
  }
  function deleteClass(cls) {
    confirmDialog("Delete class", `Delete ${local(cls.iri)} and the properties declared on it?`, () => {
      onto.classes = onto.classes.filter(c => c !== cls);
      onto.datatype_properties = onto.datatype_properties.filter(p => p.domain !== cls.iri);
      onto.object_properties = onto.object_properties.filter(p => p.domain !== cls.iri && p.range !== cls.iri);
      for (const c of onto.classes) c.parents = (c.parents || []).filter(p => p !== cls.iri);
      selected = null; render();
    }, { danger: true });
  }
  function propertyDialog(existing, domain, kind = existing?.kind) {
    const isAttr = kind === "attribute";
    const name = input({ value: existing ? local(existing.iri) : "", disabled: !!existing });
    const label = input({ value: existing?.label || "" }), desc = input({ value: existing?.description || "" });
    const range = isAttr ? select(XSD_TYPES, { value: existing?.range ? local(existing.range) : "string" })
      : select(onto.classes.map(c => ({ value: c.iri, label: local(c.iri) })), { value: existing?.range || domain });
    const traits = isAttr ? h("label", { class: "check" }, h("input", { type: "checkbox", checked: existing?.functional }), "functional (at most one value)")
      : h("div", { class: "row" }, CHARACTERISTICS.map(c => h("label", { class: "check" }, h("input", { type: "checkbox", value: c, checked: existing?.characteristics?.includes(c) }), c)));
    const inverse = isAttr ? null : select([{ value: "", label: "—" }, ...onto.object_properties.filter(p => p !== existing).map(p => ({ value: p.iri, label: local(p.iri) }))], { value: existing?.inverse_of || "" });
    const global = h("label", { class: "check" }, h("input", { type: "checkbox", checked: existing ? existing.domain === null : false }), "global (applies to every class)");
    dialog(existing ? `Edit ${local(existing.iri)}` : `New ${kind}`, h("div", {},
      field("Name", name, "lowerCamelCase; becomes the IRI local name"), h("div", { class: "form-row" }, field("Label", label), field(isAttr ? "Datatype" : "Range class", range)),
      field("Description", desc), field("Traits", traits), inverse ? field("Inverse of", inverse) : null, isAttr ? global : null),
      { confirm: existing ? "Save" : "Add", onConfirm: () => {
        const iri = existing?.iri || mint(name.value, false);
        if (!existing && (onto.datatype_properties.some(p => p.iri === iri) || onto.object_properties.some(p => p.iri === iri))) throw new Error("A property with that name exists");
        const base = { iri, label: label.value || name.value, description: desc.value || null, domain: global.querySelector("input").checked ? null : domain };
        if (isAttr) {
          const p = { ...base, range: XSD + range.value, functional: traits.querySelector("input").checked };
          const i = onto.datatype_properties.findIndex(x => x.iri === iri); i >= 0 ? onto.datatype_properties[i] = p : onto.datatype_properties.push(p);
        } else {
          const p = { ...base, range: range.value, inverse_of: inverse.value || null, characteristics: [...traits.querySelectorAll("input:checked")].map(i => i.value), sub_property_of: existing?.sub_property_of || [], chain: existing?.chain || [] };
          const i = onto.object_properties.findIndex(x => x.iri === iri); i >= 0 ? onto.object_properties[i] = p : onto.object_properties.push(p);
        }
        render();
      }});
  }
  function removeProperty(p) {
    confirmDialog("Remove property", `Remove ${local(p.iri)}?`, () => {
      onto.datatype_properties = onto.datatype_properties.filter(x => x.iri !== p.iri);
      onto.object_properties = onto.object_properties.filter(x => x.iri !== p.iri);
      render();
    }, { danger: true });
  }
  function restrictionDialog(cls) {
    const props = propsOf(cls.iri);
    const prop = select(props.map(p => ({ value: p.iri, label: `${local(p.iri)} (${p.kind})` })), {});
    const kind = select(["min", "max", "exactly", "some", "only", "has_value"], { value: "min" });
    const value = input({ value: "1" });
    dialog("Add restriction", h("div", {}, field("Property", prop), field("Kind", kind), field("Value", value, "A number for min/max/exactly; a class or datatype IRI for some/only; a literal for has_value")),
      { confirm: "Add", onConfirm: () => {
        const v = ["min", "max", "exactly"].includes(kind.value) ? Number(value.value) : value.value;
        (cls.restrictions ||= []).push({ property: prop.value, kind: kind.value, value: v }); render();
      }});
  }

  async function save() {
    try { const r = await api.put(`/versions/${vid}/ontology/json`, onto); toast(`Ontology saved · ${r.issues.filter(i => i.severity === "error").length} errors, ${r.issues.length} findings`, r.issues.some(i => i.severity === "error") ? "warn" : "ok"); }
    catch (e) { errorToast(e); }
  }
  async function showChecks() {
    try {
      const issues = await api.get(`/versions/${vid}/ontology/checks`);
      dialog("Ontology checks", issues.length ? table([{ label: "Severity", render: i => badge(i.severity) }, { label: "Code", key: "code" }, { label: "Subject", render: i => local(i.subject) }, { label: "Message", key: "message" }], issues)
        : h("p", {}, "No findings — the ontology is structurally sound."), { confirm: "Close", cancel: "Dismiss" });
    } catch (e) { errorToast(e); }
  }
  async function showTurtle() {
    const ttl = await api.text(`/versions/${vid}/ontology/turtle`);
    dialog("OWL (Turtle)", h("div", {}, h("pre", {}, ttl)), { confirm: "Download", cancel: "Close", onConfirm: () => {
      const a = h("a", { href: URL.createObjectURL(new Blob([ttl], { type: "text/turtle" })), download: `${ctx.name}-ontology.ttl` }); document.body.append(a); a.click(); a.remove(); } });
  }
  function importDialog() {
    const file = input({ type: "file", accept: ".ttl,.owl,.rdf,.xml,.jsonld,.nt" });
    const url = input({ placeholder: "https://…" });
    const fmt = select(["turtle", "xml", "json-ld", "nt", "n3"], { value: "turtle" });
    const mode = select(["merge", "replace"], { value: "merge" });
    const source = select([{ value: "", label: "—" }], {});
    api.get("/ontologies/industry").then(cat => { for (const [k, v] of Object.entries(cat)) if (v.url) source.append(h("option", { value: k }, `${v.name} (${v.licence})`)); }).catch(() => {});
    dialog("Import ontology", h("div", {}, field("File", file), field("or URL", url), field("or industry ontology", source, "Check the licence before redistributing terms."), h("div", { class: "form-row" }, field("Format", fmt), field("Mode", mode))),
      { confirm: "Import", onConfirm: async () => {
        const body = { format: fmt.value, mode: mode.value };
        if (file.files[0]) body.data = await file.files[0].text(); else if (url.value) body.url = url.value; else if (source.value) body.source = source.value; else throw new Error("Choose a file, URL or source");
        const r = await api.post(`/versions/${vid}/ontology/import`, body);
        toast(`Imported: ${r.report.classes_added} classes, ${r.report.properties_added} properties added`, "ok");
        onto = r.ontology; render();
      }});
  }
  async function autodraft() {
    const iri = input({ value: onto?.iri || ctx.domain.base_iri.replace(/\/$/, "") });
    const schema = input({ placeholder: "schema (leave empty for the default)" });
    const sel = h("select", { multiple: true, size: 10, "aria-label": "Tables" });
    const infer = h("label", { class: "check" }, h("input", { type: "checkbox", checked: true }), "infer keys from column names (for tables without declared constraints)");
    const load = async () => { sel.replaceChildren(h("option", { disabled: true }, "loading…")); try { const t = await api.get(`/catalog/tables${qs({ schema_name: schema.value })}`); sel.replaceChildren(...t.map(x => h("option", { value: x, selected: true }, x))); } catch (e) { sel.replaceChildren(h("option", { disabled: true }, e.detail || e.message)); } };
    schema.addEventListener("change", load); load();
    dialog("Draft from tables", h("div", {}, h("p", {}, "Tables become classes, columns attributes, foreign keys relationships. This also drafts the mapping."), field("Ontology IRI", iri), field("Schema", schema), field("Tables", sel, "Cmd/Ctrl-click to choose; all selected by default."), infer),
      { confirm: "Draft", onConfirm: async () => {
        const tables = [...sel.selectedOptions].filter(o => !o.disabled).map(o => o.value);
        if (!tables.length) throw new Error("Select at least one table");
        const r = await api.post(`/versions/${vid}/autodraft`, { ontology_iri: iri.value, tables, schema_name: schema.value || null, infer_keys: infer.querySelector("input").checked });
        toast(`Drafted ${r.classes} classes and ${r.relations} relations`, "ok"); ctx.reload(); } });
  }
  async function aiDraft() {
    const iri = input({ value: onto?.iri || ctx.domain.base_iri.replace(/\/$/, "") }), desc = textarea({ placeholder: "What is this data about? Any modelling guidance?" });
    dialog("Draft with AI", h("div", {}, field("Ontology IRI", iri), field("Business description", desc)), { confirm: "Draft", onConfirm: async () => {
      const r = await api.post(`/versions/${vid}/llm/draft-ontology`, { ontology_iri: iri.value, description: desc.value }); toast(`AI drafted ${r.classes} classes`, "ok"); onto = r.ontology; render(); } });
  }
  async function aiAssist() {
    const instr = textarea({ placeholder: "e.g. Add a Manager subclass of Employee with a bonus attribute" });
    dialog("AI assistant", field("Instruction", instr), { confirm: "Apply", onConfirm: async () => {
      const r = await api.post(`/versions/${vid}/llm/assist`, { instruction: instr.value }); toast("Ontology updated by the assistant", "ok"); onto = r.ontology; render(); } });
  }

  function graphView() {
    const box = h("div", { class: "graph" });
    const nodes = onto.classes.map(c => ({ id: c.iri, label: local(c.iri), color: "#0b6e4f", size: 6 + Math.min(10, propsOf(c.iri).length) }));
    const edges = [...onto.object_properties.filter(p => p.domain && p.range).map(p => ({ source: p.domain, target: p.range, label: local(p.iri) })),
      ...onto.classes.flatMap(c => (c.parents || []).map(p => ({ source: c.iri, target: p, label: "⊂" })))];
    setTimeout(() => renderGraph(box, { nodes, edges, selected, onSelect: n => { selected = n.id; mode = "list"; render(); } }), 0);
    return h("div", {}, box, h("p", { class: "muted small" }, "Drag to pan, scroll to zoom, click a class to edit it. Arrow keys move the selection."));
  }

  render();
  return root;
}
