// Domain settings: MCP policy, attachments (datasets / actions / virtual attributes / bridges), cohorts.
import { api, local } from "../api.js";
import { h, button, input, select, textarea, field, dialog, toast, errorToast, badge, table, empty, confirmDialog, tabs } from "../ui.js";

const TOOLS = ["describe_ontology", "graph_status", "list_entity_types", "search_entities", "describe_entity", "get_entity_context", "compute_virtual_attributes", "invoke_entity_action", "get_graphql_schema", "query_graphql"];

export async function settingsTab(ctx) {
  const { domain, version } = ctx; const name = ctx.name;
  const root = h("div", {}, h("h1", {}, "Settings"));
  let section = ctx.arg || "mcp";
  const body = h("div", {});
  root.append(tabs([{ id: "mcp", label: "MCP" }, { id: "attachments", label: "Attachments" }, { id: "cohorts", label: "Cohorts" }, { id: "graphql", label: "GraphQL" }], section, s => { section = s; render(); }), body);
  async function render() { body.replaceChildren(await ({ mcp, attachments, cohorts, graphql }[section])()); }

  async function mcp() {
    const policy = await api.get(`/domains/${encodeURIComponent(name)}/mcp-policy`);
    const exposed = h("label", { class: "check" }, h("input", { type: "checkbox", checked: policy.exposed !== false }), "expose this domain to MCP clients");
    const boxes = TOOLS.map(t => h("label", { class: "check" }, h("input", { type: "checkbox", value: t, checked: !(policy.disabled_tools || []).includes(t) }), t));
    return h("div", { class: "card" }, h("h2", {}, "MCP policy"), h("p", { class: "muted" }, "LLM clients connect at /mcp (Streamable HTTP) or over stdio. Registry tools (list/select domain, versions, design status) are always available."),
      exposed, h("h3", {}, "Domain tools"), h("div", { class: "grid" }, boxes), button("Save policy", { class: "primary", onClick: async () => {
        try { await api.put(`/domains/${encodeURIComponent(name)}/mcp-policy`, { exposed: exposed.querySelector("input").checked, disabled_tools: boxes.filter(b => !b.querySelector("input").checked).map(b => b.querySelector("input").value) }); toast("Policy saved", "ok"); } catch (e) { errorToast(e); } } }));
  }
  async function attachments() {
    if (!version) return empty("No version", "Create a draft first.");
    const vid = version.id; const editable = version.status === "draft";
    let att = await api.get(`/versions/${vid}/attachments`);
    const onto = version.has_ontology ? await api.get(`/versions/${vid}/ontology`) : { classes: [] };
    const classSel = () => select(onto.classes.map(c => ({ value: c.iri, label: local(c.iri) })), {});
    const save = async (next) => { try { att = await api.put(`/versions/${vid}/attachments`, next); toast("Attachments saved", "ok"); render(); } catch (e) { errorToast(e); } };
    const rm = (kind, i) => { const next = JSON.parse(JSON.stringify(att)); next[kind].splice(i, 1); save(next); };
    const sec = (title, kind, cols, add) => h("div", { class: "card" }, h("h2", {}, title, editable ? button("Add", { class: "sm primary", onClick: add }) : null),
      att[kind].length ? table([...cols, { label: "", render: (r, i) => editable ? button("Remove", { class: "sm ghost", onClick: () => rm(kind, att[kind].indexOf(r)) }) : null }], att[kind]) : h("p", { class: "muted small" }, "None."));
    return h("div", {},
      sec("Datasets", "datasets", [{ label: "Class", render: d => local(d.class_iri) }, { label: "Table", key: "table" }, { label: "Key columns", render: d => d.key_columns.join(", ") }, { label: "Description", render: d => d.description || "—" }], () => {
        const cls = classSel(), tbl = input({ placeholder: "table" }), keys = input({ placeholder: "col1,col2" }), desc = input({});
        dialog("Add dataset", h("div", {}, field("Class", cls), field("Table", tbl), field("Key columns", keys, "Columns matching the class key, in order."), field("Description", desc)), { confirm: "Add", onConfirm: () => save({ ...att, datasets: [...att.datasets, { class_iri: cls.value, table: tbl.value, key_columns: keys.value.split(",").map(s => s.trim()).filter(Boolean), description: desc.value || null }] }) }); }),
      sec("Actions", "actions", [{ label: "Class", render: a => local(a.class_iri) }, { label: "Name", key: "name" }, { label: "Kind", render: a => badge(a.kind, "neutral") }, { label: "SQL", render: a => h("code", { class: "small" }, a.sql) }], () => {
        const cls = classSel(), nm = input({ placeholder: "skills" }), sql = textarea({ placeholder: "SELECT skill FROM employee_skills WHERE empno = :empno" }), kind = select(["table", "scalar"], {}), desc = input({});
        dialog("Add action", h("div", {}, h("div", { class: "form-row" }, field("Class", cls), field("Name", nm), field("Kind", kind)), field("SQL", sql, "Use :column placeholders for the class key columns."), field("Description", desc)), { confirm: "Add", onConfirm: () => save({ ...att, actions: [...att.actions, { class_iri: cls.value, name: nm.value, sql: sql.value, kind: kind.value, description: desc.value || null }] }) }); }),
      sec("Virtual attributes", "virtual_attributes", [{ label: "Class", render: a => local(a.class_iri) }, { label: "Name", key: "name" }, { label: "SQL", render: a => h("code", { class: "small" }, a.sql) }], () => {
        const cls = classSel(), nm = input({ placeholder: "skillCount" }), sql = textarea({ placeholder: "SELECT count(*) FROM employee_skills WHERE empno = :empno" });
        dialog("Add virtual attribute", h("div", {}, h("div", { class: "form-row" }, field("Class", cls), field("Name", nm)), field("SQL (one value)", sql)), { confirm: "Add", onConfirm: () => save({ ...att, virtual_attributes: [...att.virtual_attributes, { class_iri: cls.value, name: nm.value, sql: sql.value, description: null }] }) }); }),
      sec("Bridges", "bridges", [{ label: "Class", render: b => local(b.class_iri) }, { label: "Target domain", key: "target_domain" }, { label: "Target class", render: b => local(b.target_class) }], () => {
        const cls = classSel(), dom = input({ placeholder: "payroll" }), tcls = input({ placeholder: "http://…#Worker" }), desc = input({});
        dialog("Add bridge", h("div", {}, field("Class", cls), field("Target domain", dom), field("Target class IRI", tcls), field("Description", desc)), { confirm: "Add", onConfirm: () => save({ ...att, bridges: [...att.bridges, { class_iri: cls.value, target_domain: dom.value, target_class: tcls.value, description: desc.value || null }] }) }); }));
  }
  async function cohorts() {
    if (!version) return empty("No version", "Create a draft first.");
    const vid = version.id;
    const list = await api.get(`/versions/${vid}/cohorts`);
    const onto = version.has_ontology ? await api.get(`/versions/${vid}/ontology`) : { classes: [], datatype_properties: [], object_properties: [] };
    const card = h("div", { class: "card" }, h("h2", {}, "Cohorts", button("New cohort", { class: "sm primary", onClick: () => cohortDialog(onto, vid) })),
      list.length ? table([{ label: "Name", key: "name" }, { label: "Class", render: c => local(c.class_iri) }, { label: "Match", key: "match" }, { label: "Criteria", render: c => h("span", { class: "small" }, c.criteria.map(x => `${x.kind}:${local(x.property)} ${x.operator}${x.value != null ? " " + x.value : ""}`).join(" · ")) },
        { label: "", render: c => h("span", { class: "row" }, button("Members", { class: "sm", onClick: async () => { const r = await api.get(`/versions/${vid}/cohorts/${encodeURIComponent(c.name)}/members`); dialog(`${c.name}: ${r.size} of ${r.total_candidates}`, table([{ label: "Entity", key: "label" }, { label: "Why", render: m => h("span", { class: "small" }, m.explanation.join("; ")) }], r.members), { confirm: "Close", cancel: "Dismiss" }); } }),
          button("Materialise", { class: "sm", onClick: async () => { try { const r = await api.post(`/versions/${vid}/cohorts/${encodeURIComponent(c.name)}/materialise`); toast(`${r.size} member(s) materialised`, "ok"); } catch (e) { errorToast(e); } } }),
          button("Delete", { class: "sm ghost", onClick: () => confirmDialog("Delete cohort", `Delete ${c.name}?`, async () => { await api.del(`/versions/${vid}/cohorts/${encodeURIComponent(c.name)}`); render(); }, { danger: true }) })) }], list) : h("p", { class: "muted" }, "No cohorts yet."));
    return card;
  }
  function cohortDialog(onto, vid) {
    const name = input({ placeholder: "well-paid-in-sales" }), cls = select(onto.classes.map(c => ({ value: c.iri, label: local(c.iri) })), {}), match = select(["all", "any"], {});
    const props = [...onto.datatype_properties, ...onto.object_properties];
    const rows = h("div", { class: "stack" });
    const addRow = () => rows.append(h("div", { class: "inline-form" }, select(["attribute", "relation", "related_attribute"], { "aria-label": "kind" }), select(props.map(p => ({ value: p.iri, label: local(p.iri) })), { "aria-label": "property" }),
      select(["eq", "neq", "gt", "gte", "lt", "lte", "matches", "contains", "exists", "missing", "not_exists"], { "aria-label": "operator" }), input({ placeholder: "value", "aria-label": "value" }), select([{ value: "", label: "via —" }, ...onto.datatype_properties.map(p => ({ value: p.iri, label: `via ${local(p.iri)}` }))], { "aria-label": "via" })));
    addRow();
    dialog("New cohort", h("div", {}, h("div", { class: "form-row" }, field("Name", name), field("Class", cls), field("Match", match)), h("h3", {}, "Criteria ", button("+", { class: "sm", onClick: addRow })), rows), { confirm: "Save", onConfirm: async () => {
      const criteria = [...rows.children].map(r => { const [k, p, o, v, via] = r.querySelectorAll("select, input"); let val = v.value; if (val !== "" && !isNaN(Number(val))) val = Number(val); return { kind: k.value, property: p.value, operator: o.value, value: val === "" ? null : val, via: via.value || null }; });
      await api.put(`/versions/${vid}/cohorts/${encodeURIComponent(name.value)}`, { name: name.value, class_iri: cls.value, match: match.value, criteria });
      toast("Cohort saved", "ok"); render();
    }});
  }
  async function graphql() {
    if (!version) return empty("No version", "Create a draft first.");
    const vid = version.id;
    const q = textarea({ value: "{ __schema { queryType { fields { name } } } }", rows: 6 }), out = h("pre", {}, "");
    return h("div", { class: "card" }, h("h2", {}, "GraphQL"), h("p", { class: "muted small" }, `POST /versions/${vid}/graphql`), q, h("div", { class: "row" }, button("Run", { class: "primary", onClick: async () => { try { out.textContent = JSON.stringify(await api.post(`/versions/${vid}/graphql`, { query: q.value }), null, 2); } catch (e) { errorToast(e); } } }),
      button("Schema (SDL)", { onClick: async () => { out.textContent = await api.text(`/versions/${vid}/graphql/schema`); } })), out);
  }
  await render();
  return root;
}
