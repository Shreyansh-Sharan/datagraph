import { api } from "../api.js";
import { h, table, badge, button, input, select, field, dialog, toast, errorToast, fmtDate, tabs, confirmDialog } from "../ui.js";
export async function adminView(section) {
  const root = h("div", {}, h("h1", {}, "Administration"));
  const body = h("div", {});
  const go = (id) => { location.hash = `#/admin/${id}`; };
  root.append(tabs([{ id: "principals", label: "Principals" }, { id: "keys", label: "API keys" }, { id: "locks", label: "Locks" }], section, go), body);
  body.append(await ({ principals, keys, locks }[section] || principals)());
  return root;
}
async function principals() {
  const rows = await api.get("/admin/principals");
  const name = input({ placeholder: "email or user name" });
  const role = select(["viewer", "builder", "reviewer", "admin"], { value: "builder" });
  return h("div", { class: "card" }, h("h2", {}, "Roles"),
    h("div", { class: "inline-form" }, field("Principal", name), field("Role", role), button("Set role", { class: "primary", onClick: async () => {
      try { await api.put(`/admin/principals/${encodeURIComponent(name.value.trim())}`, { role: role.value }); toast("Role saved", "ok"); location.reload(); } catch (e) { errorToast(e); } } })),
    table([{ label: "Principal", key: "name" }, { label: "Role", render: r => badge(r.role, "neutral") },
      { label: "", render: r => button("Remove", { class: "sm danger", onClick: () => confirmDialog("Remove role", `Reset ${r.name} to the default role?`, async () => { await api.del(`/admin/principals/${encodeURIComponent(r.name)}`); location.reload(); }, { danger: true }) }) }], rows));
}
async function keys() {
  const rows = await api.get("/admin/api-keys");
  const name = input({ placeholder: "ci-bot" }), principal = input({ placeholder: "ci" });
  const role = select(["viewer", "builder", "reviewer", "admin"], { value: "viewer" });
  return h("div", { class: "card" }, h("h2", {}, "API keys"),
    h("div", { class: "inline-form" }, field("Name", name), field("Principal", principal), field("Role", role), button("Issue key", { class: "primary", onClick: async () => {
      try { const k = await api.post("/admin/api-keys", { name: name.value, principal: principal.value, role: role.value });
        dialog("API key issued", h("div", {}, h("p", {}, "Copy it now — it is shown once."), h("pre", {}, k.secret)), { confirm: "Done", cancel: "Close" }); } catch (e) { errorToast(e); } } })),
    table([{ label: "Name", key: "name" }, { label: "Principal", key: "principal" }, { label: "Role", render: r => badge(r.role, "neutral") },
      { label: "Created", render: r => fmtDate(r.created_at) }, { label: "Status", render: r => r.revoked_at ? badge("revoked", "neutral") : badge("active", "ok") },
      { label: "", render: r => r.revoked_at ? null : button("Revoke", { class: "sm danger", onClick: async () => { await api.del(`/admin/api-keys/${r.id}`); location.reload(); } }) }], rows));
}
async function locks() {
  const rows = await api.get("/admin/locks");
  return h("div", { class: "card" }, h("h2", {}, "Edit locks"), rows.length ? table([
    { label: "Domain", key: "domain" }, { label: "Version", render: r => `v${r.version}` }, { label: "Editor", key: "editor" },
    { label: "Expires", render: r => fmtDate(r.lease_expires_at) }, { label: "State", render: r => r.stale ? badge("stale", "warning") : badge("active", "ok") },
    { label: "", render: r => button("Force unlock", { class: "sm danger", onClick: async () => { await api.del(`/admin/locks/${r.version_id}`); location.reload(); } }) }], rows)
    : h("p", { class: "muted" }, "No versions are locked."));
}
