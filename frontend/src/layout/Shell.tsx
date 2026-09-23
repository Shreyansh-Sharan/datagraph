import { useState } from "react";
import { Link, Outlet, useLocation, useParams, useSearchParams } from "react-router-dom";
import { Icon } from "@/components/icons";
import { Dot, EmptyState, Pill, Skeleton, Toast } from "@/components/ui";
import { Spotlight } from "@/components/Spotlight";
import { Bell } from "@/components/Bell";
import { useApp, useLoad } from "@/state/app";
import { DomainProvider, SECTIONS, sectionOf, useDomainLoad, useDomainOptional, useGo, type Screen } from "@/state/domain";
import { STATUS_COLOR, STATUS_LABEL, type Role } from "@/api";

const ROLES: Role[] = ["viewer", "builder", "reviewer", "admin"];

/** The frame of every screen. Inside a domain the domain loads here, above the top bar, so the
 *  breadcrumb can carry the version picker while the body shows its skeleton. */
export function AppShell() {
  const { toast } = useApp();
  const { name } = useParams();
  const inner = <><TopBar /><Outlet /></>;
  return (
    <div className="dg-app">
      {name ? <DomainProvider>{inner}</DomainProvider> : inner}
      <Spotlight />
      <Toast message={toast} />
    </div>
  );
}

/** Domain-scoped frame: the rail of sections on the left, the section's tab bar on top, the screen below. */
export function DomainShell() {
  const d = useDomainOptional();
  const { error } = useDomainLoad();
  if (error) return <div className="dg-body"><main className="dg-main"><EmptyState title="Domain not found" text={error} /></main></div>;
  if (!d) return <div className="dg-body"><aside className="rail" aria-label="Sections" /><main className="dg-main"><Skeleton h={44} w={320} /><Skeleton h={20} style={{ marginTop: 16 }} /><Skeleton h={20} /><Skeleton h={20} /></main></div>;
  return (
    <div className="dg-body">
      <Rail />
      <div className="dg-col">
        <SectionBar />
        <main className="dg-main"><Outlet /></main>
      </div>
    </div>
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
        <Link to="/" className={atHome ? "strong" : ""}>Domains</Link>
        {name && <DomainCrumbs />}
      </nav>
      <div className="spacer" />
      <button type="button" className="topnav spot-open" title="Ask the assistant (Cmd+K or Ctrl+K)" onClick={() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true }))}><Icon name="ask" />Ask<kbd>⌘K</kbd></button>
      <Bell />
      {can("admin") && <Link className="topnav" to="/admin" title="Admin"><Icon name="shield" />Admin</Link>}
      <SourceChip fallback={dbx ? `Databricks · ${config.catalog ?? "warehouse"}` : "Postgres"} />
      <span className="identity">
        <span style={{ fontWeight: 600 }}>{me.name}</span><span className="role">{me.role}</span>
        <select aria-label="Switch role" className="btn xxs" style={{ padding: "0 6px" }} value={me.role} onChange={e => setRole(e.target.value as Role)}>{ROLES.map(r => <option key={r} value={r}>{r}</option>)}</select>
      </span>
    </header>
  );
}

/** "Domains › name · v1 draft ▾": the domain and, once loaded, the version picker. */
function DomainCrumbs() {
  const { name = "" } = useParams();
  const go = useGo();
  return (
    <>
      <span className="sep">›</span>
      <a href="#" className="strong" onClick={e => { e.preventDefault(); go("overview"); }}>{name}</a>
      <VersionPicker />
    </>
  );
}

function VersionPicker() {
  const d = useDomainOptional();
  const go = useGo();
  const [open, setOpen] = useState(false);
  if (!d) return null;
  const { versions, version, setVersion } = d;
  const dot = version ? STATUS_COLOR[version.status] : "#B3B3B7";
  return (
    <span className="crumb-wrap">
      <button type="button" className={`crumb-ver ${open ? "open" : ""}`} aria-haspopup="listbox" aria-expanded={open} aria-label="Version" onClick={() => setOpen(o => !o)}>
        <Dot color={dot} size={7} />
        <span>{version ? `v${version.version}` : "—"} <span className="muted">{version ? STATUS_LABEL[version.status] : "no version"}</span></span>
        <Icon name="chevron" size={11} stroke="#7A7A80" />
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
    </span>
  );
}

/** The source being read: inside a domain its primary source (connection · catalog), elsewhere the deployment default. */
function SourceChip({ fallback }: { fallback: string }) {
  const { api } = useApp();
  const { name } = useParams();
  const facts = useLoad(() => name ? api.sourceFacts(name).catch(() => null) : Promise.resolve(null), [name]);
  const f = facts.data;
  const label = f ? `${f.connection ?? (f.kind === "databricks" ? "Databricks" : f.kind === "postgres" ? "Postgres" : f.kind)}${f.catalog ? ` · ${f.catalog}` : ""}` : fallback;
  return <span className="source-chip" title="Source warehouse"><Icon name="db" />{label}</span>;
}

const useScreen = () => (useLocation().pathname.split("/")[3] || "overview") as Screen;

/** The five sections of a domain, as icons down the left; Domains takes you back. */
function Rail() {
  const go = useGo();
  const current = sectionOf(useScreen());
  return (
    <aside className="rail" aria-label="Sections">
      {SECTIONS.map(s => (
        <a href="#" key={s.id} aria-current={current === s.id ? "page" : undefined} onClick={e => { e.preventDefault(); go(s.home); }}>
          <Icon name={s.icon} size={18} /><span>{s.label}</span>
        </a>
      ))}
      <Link to="/" className="rail-back"><Icon name="back" size={18} /><span>Domains</span></Link>
    </aside>
  );
}

/** The section's name and its tabs across the top of the screen; Ask has its own layout and shows none. */
function SectionBar() {
  const d = useDomainOptional();
  const go = useGo();
  const screen = useScreen();
  const [sp, setSp] = useSearchParams();
  const section = SECTIONS.find(s => s.id === sectionOf(screen))!;
  if (section.id === "ask") return null;
  if (screen === "table") {   // one table of the snapshot: back to Metadata, its name, and its three views as a capsule
    const views: [string, string][] = [["profile", "Profile"], ["dq", "Data quality"], ["glossary", "Glossary"]];
    const cur = sp.get("tab") === "dq" || sp.get("tab") === "glossary" ? sp.get("tab") : "profile";
    return (
      <div className="secbar">
        <a href="#" className="sec-back" onClick={e => { e.preventDefault(); go("metadata", { schema: sp.get("schema") ?? "", table: sp.get("table") ?? "" }); }}><Icon name="back" size={14} />Metadata</a>
        <span className="sec-title mono">{sp.get("table") || "Table"}</span>
        <nav className="seg-tabs" role="tablist" aria-label="Views">
          {views.map(([id, label]) => <a href="#" key={id} role="tab" aria-selected={cur === id} onClick={e => { e.preventDefault(); setSp(prev => { const n = new URLSearchParams(prev); n.set("tab", id); return n; }); }}>{label}</a>)}
        </nav>
      </div>
    );
  }
  const version = d?.version;
  const counts: Record<string, string | number | false> = {
    ontology: version?.stats.classes || false, mapping: version?.mappingPct != null ? `${version.mappingPct}%` : false,
    rules: version?.stats.rules || false, quality: version?.stats.constraints || false,
  };
  const active = (t: { screen: Screen; tab?: string }) => {
    const here = screen === "settings" ? "overview" : screen;
    return here === t.screen && (sp.get("tab") ?? "") === (t.tab ?? "");
  };
  return (
    <div className="secbar">
      <span className="sec-title">{section.label}</span>
      {section.tabs.length > 0 && (
        <nav className="seg-tabs" role="tablist" aria-label={section.label}>
          {section.tabs.map(t => (
            <a href="#" key={t.id} role="tab" aria-selected={active(t)} onClick={e => { e.preventDefault(); go(t.screen, t.tab ? { tab: t.tab } : {}); }}>
              {t.label}{counts[t.id] !== undefined && counts[t.id] !== false && <span className="count">{counts[t.id]}</span>}
            </a>
          ))}
        </nav>
      )}
    </div>
  );
}
