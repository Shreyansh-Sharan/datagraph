import { useState } from "react";
import { Link, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { Icon } from "@/components/icons";
import { Dot, Toast, Pill } from "@/components/ui";
import { useApp } from "@/state/app";
import { DomainProvider, useDomain, useGo, type Screen } from "@/state/domain";
import { STATUS_COLOR, STATUS_LABEL, type Role } from "@/api";

const ROLES: Role[] = ["viewer", "builder", "reviewer", "admin"];

export function AppShell() {
  const { toast } = useApp();
  return (
    <div className="dg-app">
      <TopBar />
      <Outlet />
      <Toast message={toast} />
    </div>
  );
}

/** Domain-scoped frame: side nav + version picker around the domain screens. */
export function DomainShell() {
  return (
    <DomainProvider>
      <div className="dg-body">
        <SideNav />
        <main className="dg-main"><Outlet /></main>
      </div>
    </DomainProvider>
  );
}

export function PlainMain() {
  return <div className="dg-body"><main className="dg-main"><Outlet /></main></div>;
}

function TopBar() {
  const { config, me, setRole, can } = useApp();
  const { name } = useParams();
  const loc = useLocation();
  const atHome = loc.pathname === "/";
  const dbx = config.sourceKind === "databricks";
  return (
    <header className="topbar">
      <Link className="brand" to="/"><span className="star">★</span><span>datagraph</span></Link>
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to="/" className={atHome ? "strong" : ""}>Home</Link>
        {name && <DomainCrumbs />}
      </nav>
      <div className="spacer" />
      <Link className="topnav" to="/tasks" title="My tasks"><Icon name="tasks" />My tasks<span className="count-badge">3</span></Link>
      {can("admin") && <Link className="topnav" to="/admin" title="Admin"><Icon name="shield" />Admin</Link>}
      <span className="source-chip" title="Source warehouse"><Icon name="db" />{dbx ? `Databricks · ${config.catalog ?? "warehouse"}` : "Postgres"}</span>
      <span className="identity">
        <span style={{ fontWeight: 600 }}>{me.name}</span><span className="role">{me.role}</span>
        <select aria-label="Switch role" className="btn xxs" style={{ padding: "0 6px" }} value={me.role} onChange={e => setRole(e.target.value as Role)}>{ROLES.map(r => <option key={r} value={r}>{r}</option>)}</select>
      </span>
    </header>
  );
}

function DomainCrumbs() {
  // Rendered inside the domain route only; the provider lives below in DomainShell, so read the route + a light fetch.
  const { name = "" } = useParams();
  const loc = useLocation();
  const go = useGo();
  const sp = new URLSearchParams(loc.search);
  const v = sp.get("v");
  const screen = loc.pathname.split("/")[3] ?? "";
  const pipeline: [string, Screen][] = [["Ontology", "ontology"], ["Mapping", "mapping"], ["Graph", "build"]];
  const done: Record<string, boolean> = { ontology: true, mapping: false, build: true };
  return (
    <>
      <span className="sep">›</span>
      <a href="#" className="strong" onClick={e => { e.preventDefault(); go("overview"); }}>{name}{v && <span className="muted" style={{ fontWeight: 500 }}> v{v}</span>}</a>
      {pipeline.map(([label, sc]) => (
        <span key={sc} style={{ display: "contents" }}>
          <span className="sep">›</span>
          <a href="#" className={`step ${done[sc] ? "done" : ""} ${screen === sc ? "strong" : ""}`} onClick={e => { e.preventDefault(); go(sc); }}>
            <span className="tick">{done[sc] && <Icon name="check" size={10} stroke="#fff" width={2} />}</span>{label}
          </a>
        </span>
      ))}
    </>
  );
}

function SideNav() {
  const { domain, versions, version, setVersion } = useDomain();
  const loc = useLocation();
  const navigate = useNavigate();
  const go = useGo();
  const [open, setOpen] = useState(false);
  const screen = (loc.pathname.split("/")[3] || "overview") as Screen;
  const items: [string | null, Screen, string, string | number | false][] = [
    ["Domain", "overview", "Overview", false], [null, "versions", "Versions", versions.length || false], [null, "ask", "Ask", false], [null, "settings", "Settings", false],
    ["Design", "metadata", "Metadata", 17], [null, "ontology", "Ontology", 12], [null, "mapping", "Mapping", version?.mappingPct != null ? `${version.mappingPct}%` : false], [null, "rules", "Rules", version?.stats.rules || false], [null, "quality", "Data quality", version?.stats.constraints || false],
    ["Knowledge graph", "build", "Build", false], [null, "explore", "Explore", false], [null, "triples", "Triples", false], [null, "analytics", "Analytics", false],
  ];
  const dot = version ? STATUS_COLOR[version.status] : "#B3B3B7";
  const subline = version ? (version.lease ? `lease · ${version.lease.holder}` : version.active ? "active · served to MCP" : `by ${version.by} · ${version.created}`) : "create a draft";
  return (
    <aside className="sidenav">
      <div style={{ position: "relative", margin: "0 2px 10px" }}>
        <button type="button" className={`ver-btn ${open ? "open" : ""}`} aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen(o => !o)}>
          <Dot color={dot} size={8} />
          <span style={{ flex: 1, minWidth: 0 }}>
            <span style={{ display: "block" }}>{version ? `v${version.version}` : "—"} <span className="muted" style={{ fontWeight: 500 }}>· {version ? STATUS_LABEL[version.status] : "no version"}</span></span>
            <span className="sub">{subline}</span>
          </span>
          <Icon name="chevron" size={12} stroke="#7A7A80" />
        </button>
        {open && (
          <div className="ver-menu" role="listbox">
            {versions.map(v => (
              <a href="#" key={v.version} role="option" aria-selected={v.version === version?.version} className={v.version === version?.version ? "current" : ""} onClick={e => { e.preventDefault(); setVersion(v.version); setOpen(false); }}>
                <Dot color={STATUS_COLOR[v.status]} />
                <span style={{ flex: 1, fontSize: 12.5, fontWeight: 600 }}>v{v.version} <span className="muted" style={{ fontWeight: 500 }}>{STATUS_LABEL[v.status]}</span></span>
                {v.active && <Pill tone="mini" style={{ color: "var(--blue-dark)", background: "var(--blue-soft)" }}>ACTIVE</Pill>}
              </a>
            ))}
            <a href="#" className="manage" onClick={e => { e.preventDefault(); setOpen(false); go("versions"); }}>Manage versions →</a>
          </div>
        )}
      </div>
      {items.map(([group, id, label, count]) => (
        <span key={id} style={{ display: "contents" }}>
          {group && <div className="nav-group">{group}</div>}
          <a href="#" className="nav-item" aria-current={screen === id ? "page" : undefined} onClick={e => { e.preventDefault(); if (id === "overview") navigate(`/d/${encodeURIComponent(domain.name)}${loc.search}`); else go(id); }}>
            <Icon name={id} /><span style={{ flex: 1 }}>{label}</span>{count !== false && <span className="chip">{count}</span>}
          </a>
        </span>
      ))}
    </aside>
  );
}
