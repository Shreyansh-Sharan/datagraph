// Mapping designer: class -> table, attributes -> columns, relationships via FK or link table.
import { api, local, qs } from "../api.js";
import { h, button, input, select, field, dialog, toast, errorToast, badge, table, empty, kpis, pct, progress, confirmDialog } from "../ui.js";

export async function mappingTab(ctx) {
  const { version } = ctx; const vid = version.id;
  const editable = version.status === "draft";
  if (!version.has_ontology) return empty("Design the ontology first", "Mappings bind ontology classes to tables.", h("a", { class: "btn", href: `#/d/${encodeURIComponent(ctx.name)}/ontology` }, "Go to ontology"));
  const onto = await api.get(`/versions/${vid}/ontology`);
  let spec = version.has_mapping ? await api.get(`/versions/${vid}/mapping`) : { base_iri: ctx.domain.base_iri, classes: [], relations: [] };
  let status = await api.get(`/versions/${vid}/mapping/status`);
  const tables = await api.get("/catalog/tables").catch(() => []);
  const columnsCache = {};
  const columnsOf = async (t) => columnsCache[t] ||= (await api.get(`/catalog/tables/${encodeURIComponent(t)}`)).columns.map(c => c.name);
  let selected = ctx.arg || onto.classes[0]?.iri;
  const root = h("div", {}), head = h("div", { class: "page-head" }), stats = h("div", {}), body = h("div", {});
  root.append(head, stats, body);

  async function persist(msg = "Mapping saved") {
    try { spec = await api.put(`/versions/${vid}/mapping`, spec); status = await api.get(`/versions/${vid}/mapping/status`); toast(msg, "ok"); render(); }
    catch (e) { errorToast(e); }
  }
  const classSpec = (iri) => spec.classes.find(c => c.class_iri === iri);
  const propsOf = (iri) => { const anc = ancestors(iri); return { attrs: onto.datatype_properties.filter(p => p.domain === iri || p.domain === null || anc.includes(p.domain)), rels: onto.object_properties.filter(p => p.domain === iri || anc.includes(p.domain)) }; };
  function ancestors(iri) { const out = []; const stack = [...(onto.classes.find(c => c.iri === iri)?.parents || [])]; while (stack.length) { const p = stack.shift(); if (out.includes(p)) continue; out.push(p); stack.push(...(onto.classes.find(c => c.iri === p)?.parents || [])); } return out; }

  function render() {
    const s = status.summary;
    head.replaceChildren(h("div", {}, h("h1", {}, "Mapping"), h("p", { class: "muted" }, "Bind each class to a table and its attributes to columns; relationships follow foreign keys or link tables.")),
      h("div", { class: "actions" },
        editable ? button("Draft from tables", { onClick: autodraft }) : null, editable ? button("Suggest with AI", { onClick: aiSuggest }) : null,
        editable ? button("Exclude unmapped", { onClick: () => confirmDialog("Exclude unmapped", "Mark every unmapped attribute and relationship as excluded?", async () => { spec = await api.post(`/versions/${vid}/mapping/exclude-unmapped`); status = await api.get(`/versions/${vid}/mapping/status`); render(); }) }) : null,
        button("Drift", { onClick: showDrift }), button("R2RML", { onClick: () => showText(`/versions/${vid}/mapping/r2rml`, "R2RML (Turtle)") }),
        button("SQL", { onClick: showSql })));
    stats.replaceChildren(kpis([["Completion", pct(status.completion)], ["Classes mapped", `${s.mapped_classes}/${s.classes}`], ["Attributes", `${s.mapped_attributes}/${s.attributes}`], ["Relationships", `${s.mapped_relations}/${s.relations}`], ["Excluded", s.excluded_attributes + s.excluded_relations]]), progress(status.completion));
    body.replaceChildren(h("div", { class: "split" }, classList(), selected ? classPanel(selected) : h("div", { class: "card muted" }, "Select a class.")));
  }
  function classList() {
    return h("div", { class: "card" }, h("h2", {}, "Classes"), h("ul", { class: "list" }, status.classes.map(c => h("li", { class: c.class_iri === selected ? "selected" : "" },
      h("a", { href: "#", onClick: e => { e.preventDefault(); selected = c.class_iri; render(); } }, local(c.class_iri), c.table ? h("span", { class: "muted small" }, ` → ${c.table}`) : null),
      h("span", { class: "row" }, badge(c.state), h("span", { class: "muted small" }, pct(c.completion)))))));
  }
  function classPanel(iri) {
    const cm = classSpec(iri); const st = status.classes.find(c => c.class_iri === iri) || {};
    const { attrs, rels } = propsOf(iri);
    if (!cm) return h("div", { class: "card" }, h("h2", {}, local(iri), badge("unmapped")), h("p", { class: "muted" }, "This class has no table yet."),
      editable ? button("Map to a table", { class: "primary", onClick: () => tableDialog(iri) }) : null);
    const excluded = new Set(cm.excluded || []);
    const attrRows = table([
      { label: "Attribute", render: p => local(p.iri) },
      { label: "Column", render: p => { const b = cm.attributes.find(a => a.property_iri === p.iri); return b ? h("span", { class: "mono" }, b.column) : excluded.has(p.iri) ? badge("excluded", "neutral") : badge("unmapped"); } },
      { label: "", render: p => editable ? h("span", { class: "row" }, button(cm.attributes.some(a => a.property_iri === p.iri) ? "Change" : "Bind", { class: "sm", onClick: () => bindDialog(cm, p) }),
        button(excluded.has(p.iri) ? "Include" : "Exclude", { class: "sm ghost", onClick: async () => { spec = await api.post(`/versions/${vid}/mapping/exclude`, { class_iri: iri, property_iri: p.iri, excluded: !excluded.has(p.iri) }); status = await api.get(`/versions/${vid}/mapping/status`); render(); } })) : null },
    ], attrs);
    const relRows = table([
      { label: "Relationship", render: p => `${local(p.iri)} → ${local(p.range || "")}` },
      { label: "Mapping", render: p => { const r = spec.relations.find(x => x.property_iri === p.iri && x.source_class === iri); if (!r) return excluded.has(p.iri) ? badge("excluded", "neutral") : badge("unmapped");
        return h("span", { class: "mono small" }, r.table ? `${r.table} (${(r.source_key || []).join(",")} → ${(r.target_key || []).join(",")})` : `FK ${(r.target_key || []).join(",")}`, r.direction && r.direction !== "forward" ? ` · ${r.direction}` : ""); } },
      { label: "", render: p => editable ? h("span", { class: "row" }, button("Map", { class: "sm", onClick: () => relationDialog(cm, p) }),
        button(excluded.has(p.iri) ? "Include" : "Exclude", { class: "sm ghost", onClick: async () => { spec = await api.post(`/versions/${vid}/mapping/exclude`, { class_iri: iri, property_iri: p.iri, excluded: !excluded.has(p.iri) }); status = await api.get(`/versions/${vid}/mapping/status`); render(); } })) : null },
    ], rels);
    return h("div", { class: "card" },
      h("h2", {}, h("span", {}, local(iri), " ", badge(st.state || "partial")), h("span", { class: "row" }, button("Preview", { class: "sm", onClick: () => preview(iri) }), editable ? button("Change table", { class: "sm", onClick: () => tableDialog(iri, cm) }) : null, editable ? button("Unmap", { class: "sm danger", onClick: () => confirmDialog("Unmap class", `Remove the mapping of ${local(iri)} and its relationships?`, async () => { spec = await api.del(`/versions/${vid}/mapping/classes?class_iri=${encodeURIComponent(iri)}`); status = await api.get(`/versions/${vid}/mapping/status`); render(); }, { danger: true }) }) : null)),
      h("p", { class: "small muted mono" }, `${cm.table || cm.sql_query} · key: ${cm.key_columns.join(", ")}${cm.iri_template ? " · " + cm.iri_template : ""}`),
      h("h3", {}, "Attributes"), attrs.length ? attrRows : h("p", { class: "muted small" }, "No attributes on this class."),
      h("h3", {}, "Relationships"), rels.length ? relRows : h("p", { class: "muted small" }, "No relationships from this class."));
  }
  function tableDialog(iri, cm) {
    const tbl = select(["", ...tables], { value: cm?.table || "" }); const sqlq = input({ value: cm?.sql_query || "", placeholder: "or a SELECT query" });
    const keys = h("select", { multiple: true, size: 5 }); const tpl = input({ value: cm?.iri_template || "", placeholder: `${spec.base_iri}${local(iri)}/{id}` });
    const fillKeys = async () => { keys.replaceChildren(); if (!tbl.value) return; try { const info = await api.get(`/catalog/tables/${encodeURIComponent(tbl.value)}`); for (const c of info.columns) keys.append(h("option", { value: c.name, selected: (cm?.key_columns || info.primary_key).includes(c.name) }, `${c.name} (${c.type})`)); } catch (e) { errorToast(e); } };
    tbl.addEventListener("change", fillKeys); fillKeys();
    dialog(`Map ${local(iri)} to a table`, h("div", {}, field("Table", tbl), field("SQL query (instead of a table)", sqlq), field("Key columns", keys, "Identify one instance; combined into the entity IRI."), field("IRI template (optional)", tpl)),
      { confirm: "Save", onConfirm: async () => {
        const entry = { class_iri: iri, table: tbl.value || null, sql_query: tbl.value ? null : (sqlq.value || null), key_columns: [...keys.selectedOptions].map(o => o.value), iri_template: tpl.value || null, attributes: cm?.attributes || [], excluded: cm?.excluded || [] };
        if (!entry.table && !entry.sql_query) throw new Error("Choose a table or give a query");
        if (!entry.key_columns.length && !entry.iri_template) throw new Error("Choose key columns");
        const i = spec.classes.findIndex(c => c.class_iri === iri); i >= 0 ? spec.classes[i] = entry : spec.classes.push(entry);
        await persist();
      }});
  }
  async function bindDialog(cm, prop) {
    const cols = cm.table ? await columnsOf(cm.table) : [];
    const col = cols.length ? select(["", ...cols], { value: cm.attributes.find(a => a.property_iri === prop.iri)?.column || "" }) : input({ value: cm.attributes.find(a => a.property_iri === prop.iri)?.column || "" });
    dialog(`Bind ${local(prop.iri)}`, field("Column", col), { confirm: "Save", onConfirm: async () => {
      cm.attributes = cm.attributes.filter(a => a.property_iri !== prop.iri);
      if (col.value) cm.attributes.push({ property_iri: prop.iri, column: col.value, datatype: null, language: null });
      await persist();
    }});
  }
  async function relationDialog(cm, prop) {
    const existing = spec.relations.find(x => x.property_iri === prop.iri && x.source_class === cm.class_iri);
    const targets = spec.classes.map(c => ({ value: c.class_iri, label: local(c.class_iri) }));
    if (!targets.some(t => t.value === prop.range)) toast(`Map ${local(prop.range)} to a table first for a complete relationship`, "warn");
    const target = select(targets, { value: existing?.target_class || prop.range });
    const mode = select([{ value: "fk", label: "Foreign key on this table" }, { value: "link", label: "Link table" }], { value: existing?.table ? "link" : "fk" });
    const link = select(["", ...tables], { value: existing?.table || "" }); const skey = input({ value: (existing?.source_key || []).join(","), placeholder: "columns in the link table → this class" });
    const tkey = input({ value: (existing?.target_key || []).join(","), placeholder: "columns → target class key" });
    const direction = select(["forward", "reverse", "bidirectional"], { value: existing?.direction || "forward" });
    dialog(`Map ${local(prop.iri)}`, h("div", {}, field("Target class", target), field("How", mode), field("Link table (link mode)", link), field("Source key columns (link mode)", skey), field("Target key columns", tkey, "Comma-separated; must match the target class key arity."), field("Direction", direction)),
      { confirm: "Save", onConfirm: async () => {
        const entry = { property_iri: prop.iri, source_class: cm.class_iri, target_class: target.value, table: mode.value === "link" ? link.value || null : null, sql_query: null,
          source_key: mode.value === "link" ? skey.value.split(",").map(s => s.trim()).filter(Boolean) : null, target_key: tkey.value.split(",").map(s => s.trim()).filter(Boolean), direction: direction.value };
        spec.relations = spec.relations.filter(x => !(x.property_iri === prop.iri && x.source_class === cm.class_iri)); spec.relations.push(entry);
        await persist();
      }});
  }
  async function preview(iri) {
    try { const r = await api.get(`/versions/${vid}/mapping/preview${qs({ class_iri: iri, limit: 20 })}`);
      dialog(`Preview: ${local(iri)}`, r.rows.length ? table(r.columns.map(c => ({ label: c, render: row => h("span", { class: "mono small" }, row[c] ?? "—") })), r.rows) : h("p", {}, "The query returned no rows."), { confirm: "Close", cancel: "Dismiss" }); }
    catch (e) { errorToast(e); }
  }
  async function showDrift() {
    try { const issues = await api.get(`/versions/${vid}/mapping/drift`);
      dialog("Schema drift", issues.length ? table([{ label: "Severity", render: i => badge(i.severity) }, { label: "Kind", key: "kind" }, { label: "Table", key: "table" }, { label: "Column", render: i => i.column || "—" }, { label: "Depends", key: "mapping_ref" }, { label: "Detail", key: "detail" }], issues) : h("p", {}, "No drift: every table and column the mapping uses exists with the snapshotted type."), { confirm: "Close", cancel: "Dismiss" }); }
    catch (e) { errorToast(e); }
  }
  async function showText(url, title) { try { const t = await api.text(url); dialog(title, h("pre", {}, t), { confirm: "Close", cancel: "Dismiss" }); } catch (e) { errorToast(e); } }
  async function showSql() {
    const d = select(["postgres", "databricks", "sqlite"], { value: "databricks" });
    const pre = h("pre", {}, "…");
    const load = async () => { pre.textContent = await api.text(`/versions/${vid}/mapping/sql?dialect=${d.value}`); };
    d.addEventListener("change", load); load();
    dialog("Compiled SQL", h("div", {}, field("Dialect", d), pre), { confirm: "Close", cancel: "Dismiss" });
  }
  async function autodraft() {
    confirmDialog("Draft from tables", "Replace the ontology and mapping with a draft derived from the catalog's keys?", async () => { const r = await api.post(`/versions/${vid}/autodraft`, { ontology_iri: onto.iri }); toast(`Drafted ${r.classes} classes, ${r.relations} relations`, "ok"); ctx.reload(); });
  }
  async function aiSuggest() {
    confirmDialog("Suggest with AI", "Ask the model to propose the mapping from the ontology and table metadata? The current mapping is replaced.", async () => { const r = await api.post(`/versions/${vid}/llm/suggest-mapping`, {}); toast(`AI mapped ${r.classes} classes and ${r.relations} relations`, "ok"); ctx.reload(); });
  }
  render();
  return root;
}
