import { useNavigate } from "react-router-dom";
import { Icon } from "@/components/icons";
import { Skeleton } from "@/components/ui";
import { useApp, useLoad } from "@/state/app";

export function Tasks() {
  const { api } = useApp();
  const navigate = useNavigate();
  const tasks = useLoad(() => api.tasks(), []);
  return (
    <>
      <div className="page-head"><div><h1>My tasks</h1><p>Reviews waiting for you, your leases, and your failed builds.</p></div></div>
      <div className="grid" style={{ gap: 12, maxWidth: 900 }}>
        {tasks.loading && <Skeleton h={62} />}
        {(tasks.data ?? []).map(t => (
          <a key={t.title} href="#" onClick={e => { e.preventDefault(); const q = t.go.version ? `?v=${t.go.version}` : ""; navigate(t.go.domain ? `/d/${t.go.domain}/${t.go.screen}${q}` : `/${t.go.screen}`); }}
            style={{ display: "grid", gridTemplateColumns: "auto 1fr auto", gap: 14, alignItems: "center", background: "#fff", border: "1px solid var(--line)", borderRadius: 10, padding: "14px 18px", color: "var(--ink)" }}>
            <span style={{ width: 32, height: 32, borderRadius: 8, background: "var(--blue-soft)", color: "var(--blue)", display: "inline-flex", alignItems: "center", justifyContent: "center" }}><Icon name={t.icon} /></span>
            <span><div style={{ fontWeight: 700 }}>{t.title}</div><div className="muted small">{t.sub}</div></span>
            <span className="muted-2 small">{t.when}</span>
          </a>
        ))}
      </div>
    </>
  );
}
