import { api } from "../api.js";
import { h, table, badge, empty } from "../ui.js";
export async function tasksView() {
  const t = await api.get("/tasks");
  const section = (title, rows, note) => h("div", { class: "card" }, h("h2", {}, title), rows.length ? table([
    { label: "Domain", render: r => h("a", { href: `#/d/${encodeURIComponent(r.domain)}/overview` }, r.domain) },
    { label: "Version", render: r => `v${r.version}` }, { label: "Status", render: r => badge(r.status) },
    { label: "Editor", render: r => r.editor || "—" }, { label: "Approvals", render: r => `${r.approvals}/${r.quorum}` },
  ], rows) : h("p", { class: "muted" }, note));
  return h("div", {}, h("h1", {}, "My tasks"),
    section("Drafts in progress", t.drafts, "No drafts."), section("Waiting for my review", t.to_review, "Nothing to review."),
    section("Ready to publish", t.publishable, "Nothing has reached its quorum."));
}
