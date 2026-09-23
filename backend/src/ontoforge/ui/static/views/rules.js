// SWRL rules: author in presentation syntax, materialise or check for violations.
import { api, local } from "../api.js";
import { h, button, input, select, textarea, field, dialog, toast, errorToast, badge, table, empty, confirmDialog } from "../ui.js";

export async function rulesTab(ctx) {
  const { version } = ctx; const vid = version.id; const editable = version.status === "draft";
  let rs = await api.get(`/versions/${vid}/rules`);
  const root = h("div", {}), body = h("div", {});
  root.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Rules"), h("p", { class: "muted" }, "SWRL rules in presentation syntax. Materialise rules add triples; violation rules report matches.")),
    h("div", { class: "actions" }, editable ? button("Add rule", { class: "primary", onClick: () => ruleDialog() }) : null, button("SQL", { onClick: async () => { try { dialog("Compiled SQL", h("pre", {}, await api.text(`/versions/${vid}/rules/sql`)), { confirm: "Close", cancel: "Dismiss" }); } catch (e) { errorToast(e); } } }),
      button("Run rules", { onClick: run }))), body);
  function render() {
    body.replaceChildren(rs.rules.length ? table([
      { label: "Name", render: r => h("strong", {}, r.name) }, { label: "Rule", render: r => h("code", {}, r.text) }, { label: "Mode", render: r => badge(r.mode, "neutral") },
      { label: "Enabled", render: r => r.enabled ? badge("on", "ok") : badge("off", "neutral") },
      { label: "", render: r => editable ? h("span", { class: "row" }, button("Edit", { class: "sm", onClick: () => ruleDialog(r) }), button("Remove", { class: "sm ghost", onClick: () => confirmDialog("Remove rule", `Remove ${r.name}?`, () => save(rs.rules.filter(x => x.name !== r.name)), { danger: true }) })) : null },
    ], rs.rules) : empty("No rules", "Example: Employee(?e) ^ salary(?e, ?s) ^ swrlb:greaterThan(?s, 100000) -> HighEarner(?e)"));
  }
  async function save(rules) { try { rs = await api.put(`/versions/${vid}/rules`, { rules: rules.map(r => ({ name: r.name, text: r.text, mode: r.mode, enabled: r.enabled })) }); toast("Rules saved", "ok"); render(); } catch (e) { errorToast(e); } }
  function ruleDialog(existing) {
    const name = input({ value: existing?.name || "", disabled: !!existing }), text = textarea({ value: existing?.text || "", rows: 3 });
    const mode = select(["materialize", "violation"], { value: existing?.mode || "materialize" }); const enabled = h("label", { class: "check" }, h("input", { type: "checkbox", checked: existing ? existing.enabled : true }), "enabled");
    dialog(existing ? `Edit ${existing.name}` : "New rule", h("div", {}, field("Name", name), field("Rule", text, "body atoms joined by ^, then -> and the head. Built-ins: swrlb:equal, notEqual, lessThan, lessThanOrEqual, greaterThan, greaterThanOrEqual."), h("div", { class: "form-row" }, field("Mode", mode), field("", enabled))),
      { confirm: "Save", onConfirm: async () => {
        const r = { name: name.value.trim(), text: text.value.trim(), mode: mode.value, enabled: enabled.querySelector("input").checked };
        const others = rs.rules.filter(x => x.name !== r.name);
        await save([...others, r]);
      }});
  }
  async function run() { try { const r = await api.post(`/versions/${vid}/reasoning/rules`);
    dialog("Rules run", h("div", {}, h("p", {}, `${r.materialised} triple(s) materialised in ${r.iterations} iteration(s).`), r.violations.length ? table([{ label: "Rule", key: "rule" }, { label: "Bindings", render: v => h("code", {}, JSON.stringify(v.bindings)) }], r.violations) : h("p", { class: "muted" }, "No violations.")), { confirm: "Close", cancel: "Dismiss" }); } catch (e) { errorToast(e); } }
  render();
  return root;
}
