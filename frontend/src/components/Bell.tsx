// The bell: the unread count, and a list of everything that happened, running work first, each
// row a link to where it happened. Opening the list marks what is shown as read after a moment.
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Icon } from "@/components/icons";
import { Spinner } from "@/components/ui";
import { relTime } from "@/api/format";
import { useApp, useLoad } from "@/state/app";
import { useNotifications } from "@/state/notifications";
import type { Notification } from "@/api";

const ICON: Record<string, string> = { build: "build", job: "ask", profile: "metadata", dq: "quality", glossary: "rules", metadata: "metadata", status: "versions", review: "versions", comment: "overview",
  lease: "overview", version: "versions", content: "ontology", domain: "settings", mcp_policy: "settings", drift: "warn" };

export function href(n: Notification): string {
  const l = n.link || {};
  if (!l.domain) return "/";
  const q = new URLSearchParams();
  if (l.version != null) q.set("v", String(l.version));
  for (const k of ["schema", "table", "tab", "cls"] as const) if (l[k]) q.set(k, String(l[k]));
  const qs = q.toString();
  return `/d/${encodeURIComponent(String(l.domain))}/${l.screen || "overview"}${qs ? `?${qs}` : ""}`;
}

export function Bell() {
  const { api } = useApp();
  const { items, unread, running, markRead, stale } = useNotifications();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const tasks = useLoad(() => open ? api.tasks().catch(() => []) : Promise.resolve(null), [open]);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away); window.addEventListener("keydown", key);
    const t = setTimeout(() => { const shown = items.filter(n => !n.read).map(n => n.id); if (shown.length) void markRead(shown); }, 1500);   // what was seen is read
    return () => { document.removeEventListener("mousedown", away); window.removeEventListener("keydown", key); clearTimeout(t); };
  }, [open]);   // eslint-disable-line react-hooks/exhaustive-deps
  const go = (n: Notification) => { if (!n.read) void markRead([n.id]); setOpen(false); navigate(href(n)); };
  const active = items.filter(n => n.status === "running"), rest = items.filter(n => n.status !== "running");
  return (
    <div className="bell-wrap" ref={box}>
      <button type="button" className={`topnav bell ${open ? "on" : ""}`} aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`} aria-expanded={open} aria-haspopup="menu" title={stale ? "The last check failed; showing what was known" : "Notifications"} onClick={() => setOpen(o => !o)}>
        <Icon name="bell" />
        {running > 0 && <Spinner blue />}
        {unread > 0 && <span className="count-badge">{unread > 99 ? "99+" : unread}</span>}
        {stale && <i className="bell-stale" aria-label="Notifications may be out of date" />}
      </button>
      {open && (
        <div className="bell-menu" role="menu" aria-label="Notifications">
          <div className="row between bell-head"><strong>Activity</strong><span className="row" style={{ gap: 12 }}>{unread > 0 && items.length > 0 && <a href="#" className="small" onClick={e => { e.preventDefault(); void markRead(undefined, Math.max(...items.map(n => n.id))); }}>Mark all read</a>}<Link to="/tasks" className="small" onClick={() => setOpen(false)}>All tasks</Link></span></div>
          {active.length > 0 && <div className="bell-section">Running</div>}
          {active.map(n => <Row key={n.id} n={n} onOpen={go} />)}
          {tasks.data && tasks.data.length > 0 && <div className="bell-section">Needs you</div>}
          {(tasks.data ?? []).map(t => (
            <button type="button" key={t.title} role="menuitem" className="bell-row" onClick={() => { setOpen(false); const q = t.go.version ? `?v=${t.go.version}` : ""; navigate(t.go.domain ? `/d/${t.go.domain}/${t.go.screen}${q}` : `/${t.go.screen}`); }}>
              <span className="bell-ic"><Icon name={t.icon} size={14} /></span><span className="bell-body"><span className="bell-title">{t.title}</span><span className="muted xs">{t.sub}</span></span>
            </button>))}
          {rest.length > 0 && <div className="bell-section">Recent</div>}
          {rest.slice(0, 40).map(n => <Row key={n.id} n={n} onOpen={go} />)}
          {items.length === 0 && (!tasks.data || tasks.data.length === 0) && <p className="muted small" style={{ padding: "14px 16px" }}>Nothing yet. Builds, profiles, rule runs and design changes will show up here.</p>}
        </div>
      )}
    </div>
  );
}

function Row({ n, onOpen }: { n: Notification; onOpen: (n: Notification) => void }) {
  const kind = n.kind.split(".")[0];
  return (
    <button type="button" role="menuitem" className={`bell-row ${n.read ? "" : "unread"} ${n.status}`} onClick={() => onOpen(n)}>
      <span className={`bell-ic ${n.status}`}>{n.status === "running" ? <Spinner blue /> : <Icon name={ICON[kind] ?? "overview"} size={14} />}</span>
      <span className="bell-body">
        <span className="bell-title">{n.title}</span>
        {n.status === "running" && n.progress && <span className="xs" style={{ color: "var(--blue-dark)" }}>{n.progress}</span>}
        {n.body && n.status !== "running" && <span className="muted xs">{n.body}</span>}
        <span className="muted-2 xs">{n.actor ?? "system"}{n.via ? ` · via ${n.via}` : ""} · {relTime(n.status === "running" ? n.created_at : n.updated_at)}</span>
      </span>
      {!n.read && <i className="bell-dot" aria-hidden="true" />}
    </button>
  );
}
