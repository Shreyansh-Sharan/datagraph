// Metadata: snapshot source tables into the version, refresh, comment columns, see drift.
import { api, local } from "../api.js";
import { h, button, input, field, dialog, toast, errorToast, badge, table, empty, fmtDate, confirmDialog } from "../ui.js";

export async function metadataTab(ctx) {
  const { version } = ctx; const vid = version.id; const editable = version.status === "draft";
  const root = h("div", {});
  let snaps = await api.get(`/versions/${vid}/metadata`);
  const head = h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Metadata"), h("p", { class: "muted" }, "A snapshot of the source tables this version was designed against. Comments here feed the AI and document meaning.")),
    h("div", { class: "actions" }, editable ? button("Import tables", { class: "primary", onClick: importDialog }) : null, editable && snaps.length ? button("Refresh from catalog", { onClick: refresh }) : null));
  const body = h("div", {});
  root.append(head, body);
  function render() {
    body.replaceChildren(snaps.length ? snaps.map(snapCard) : empty("No tables imported", "Import the tables this domain maps so their columns, keys and comments are recorded with the version.",
      editable ? button("Import tables", { class: "primary", onClick: importDialog }) : null));
  }
  function snapCard(s) {
    return h("div", { class: "card" }, h("h2", {}, h("span", {}, s.table, " ", h("span", { class: "muted small" }, s.comment || "")), h("span", { class: "row" }, h("span", { class: "muted small" }, `captured ${fmtDate(s.captured_at)}`),
      editable ? button("Remove", { class: "sm ghost", onClick: () => confirmDialog("Remove table", `Remove ${s.table} from this version's metadata?`, async () => { await api.del(`/versions/${vid}/metadata/${encodeURIComponent(s.table)}`); snaps = await api.get(`/versions/${vid}/metadata`); render(); }, { danger: true }) }) : null)),
      h("p", { class: "small muted" }, `key: ${s.primary_key.join(", ") || "—"}`, s.foreign_keys.length ? ` · FKs: ${s.foreign_keys.map(f => `${f.columns.join(",")} → ${f.references}`).join("; ")}` : ""),
      table([{ label: "Column", render: c => h("span", { class: "mono" }, c.name) }, { label: "Type", key: "type" },
        { label: "Comment", render: c => editable ? commentEditor(s.table, c) : (c.comment || h("span", { class: "muted" }, "—")) }], s.columns));
  }
  function commentEditor(t, c) {
    const i = input({ value: c.comment || "", placeholder: "describe this column", "aria-label": `Comment for ${c.name}` });
    i.addEventListener("change", async () => { try { await api.put(`/versions/${vid}/metadata/${encodeURIComponent(t)}/columns/${encodeURIComponent(c.name)}`, { comment: i.value || null }); toast("Comment saved", "ok"); } catch (e) { errorToast(e); } });
    return i;
  }
  async function importDialog() {
    const all = await api.get("/catalog/tables").catch(() => []);
    const have = new Set(snaps.map(s => s.table));
    const sel = h("select", { multiple: true, size: Math.min(12, Math.max(4, all.length)) }, all.map(t => h("option", { value: t, selected: have.has(t) }, t)));
    dialog("Import tables", field("Tables", sel, "Cmd/Ctrl-click to select several."), { confirm: "Import", onConfirm: async () => {
      const tables = [...sel.selectedOptions].map(o => o.value); if (!tables.length) throw new Error("Select at least one table");
      snaps = await api.post(`/versions/${vid}/metadata/import`, { tables }); toast(`Imported ${tables.length} table(s)`, "ok"); render(); } });
  }
  async function refresh() {
    try { const changes = await api.post(`/versions/${vid}/metadata/refresh`); snaps = await api.get(`/versions/${vid}/metadata`); render();
      dialog("Refresh result", changes.length ? table([{ label: "Table", key: "table" }, { label: "Missing", render: c => c.missing ? badge("gone", "error") : "—" }, { label: "Added", render: c => c.added.join(", ") || "—" }, { label: "Removed", render: c => c.removed.join(", ") || "—" }, { label: "Type changes", render: c => c.modified.map(m => `${m.column}: ${m.from} → ${m.to}`).join("; ") || "—" }], changes) : h("p", {}, "Nothing changed in the catalog."), { confirm: "Close", cancel: "Dismiss" }); }
    catch (e) { errorToast(e); }
  }
  render();
  return root;
}
