import { useState } from "react";
import { Button, Card, Dot, ErrorNotice, Pill, Skeleton, Spinner, Tabs } from "@/components/ui";
import { Icon } from "@/components/icons";
import { useApp, useLoad } from "@/state/app";
import { useDomain, useGo, useParam } from "@/state/domain";
import { tableName } from "@/api";

type Tab = "columns" | "dq" | "onto" | "glossary";
const BLUE = "#2249FF", ORANGE = "#FF7000", GREY = "#B3B3B7", DARK = "#1636E0";

const full0 = (schema: string, table: string) => (schema ? `${schema}.${table}` : table);

export function Metadata() {
  const { api, config, say } = useApp();
  const { domain, version, editable } = useDomain();
  const go = useGo();
  const dbx = config.sourceKind === "databricks";
  const [schemaParam, setSchema] = useParam("schema", "");
  const [tableParam, setTable] = useParam("table", "");
  const [selected, setSelected] = useState<string[]>([]);
  const [importing, setImporting] = useState(false);
  const [tab, setTab] = useParam("tab", "columns");
  const [gq, setGq] = useParam("gq", "");
  const [search, setSearch] = useState("");
  const [profiled, setProfiled] = useState(false);
  const [dqRan, setDqRan] = useState(false);
  const [gScope, setGScope] = useState(false);
  const [applied, setApplied] = useState<string[]>([]);

  const schemas = useLoad(() => api.schemas(domain.name), [domain.name]);
  const schema = schemaParam || schemas.data?.[0]?.id || "";
  const tables = useLoad(() => schema ? api.catalogTables(domain.name, schema, version?.version) : Promise.resolve([]), [domain.name, schema, version?.version]);
  const table = tableParam || tables.data?.[0]?.name || "";
  const detail = useLoad(() => table ? api.tableDetail(domain.name, schema, table) : Promise.resolve(null), [domain.name, schema, table]);
  const profile = useLoad(() => profiled ? api.tableProfile(domain.name, table) : Promise.resolve(null), [domain.name, table, profiled]);
  const dq = useLoad(() => api.tableDq(domain.name, table), [domain.name, table]);
  const glossary = useLoad(() => api.glossary(domain.name), [domain.name]);
  const diffs = useLoad(() => api.ontoDiffs(domain.name, table), [domain.name, table]);
  const tcls = useLoad(() => table ? api.tableClass(domain.name, full0(schema, table), version?.version) : Promise.resolve(null), [domain.name, schema, table, version?.version]);
  const caps = config.capabilities;

  const cols = detail.data?.columns ?? [];
  const full = detail.data?.fullName ?? (schema.includes(".") ? full0(schema, table) : tableName(config.sourceKind, domain.catalog, schema, table));
  const cls = tcls.data ?? null;
  const dqIssues = (dq.data ?? []).filter(d => d.kind !== "—");
  const diffsLeft = (diffs.data ?? []).filter(d => !applied.includes(`${table}:${d.column}`));
  const termByCol = Object.fromEntries((glossary.data ?? []).flatMap(g => g.cols.map(c => [c.split(".")[1], g.term])));
  const catList = tables.data ?? [];
  const imported = catList.find(t => t.name === table)?.imported ?? false;
  const prof = profile.data;

  const dqRows = [
    ...dqIssues.map(d => { const n = parseInt(d.count) || 0; return { name: d.kind === "drift" ? "Target table exists" : d.kind === "pattern" ? "Country is ISO-2" : "Quantity is positive", column: d.column, kind: d.kind, severity: d.kind === "pattern" ? "warning" : "violation", dot: d.kind === "pattern" ? GREY : ORANGE, count: n || "—", bad: n > 0, sample: n ? `${cls || "Row"}/… ${n} rows` : "—" }; }),
    ...(dqRan && cols[0] ? [{ name: "Key is unique", column: cols[0].name, kind: "unique", severity: "violation", dot: ORANGE, count: prof?.dup ?? "0", bad: !!prof && prof.dup !== "0" && prof.dup !== "—", sample: "—" }, { name: "Key not null", column: cols[0].name, kind: "min_count", severity: "violation", dot: ORANGE, count: 0, bad: false, sample: "—" }] : []),
  ];
  const openViolations = dqRows.reduce((a, r) => a + (typeof r.count === "number" ? r.count : 0), 0);
  const glossaryRows = (glossary.data ?? []).filter(g => !gScope || g.cols.some(c => c.startsWith(`${table}.`))).filter(g => { const t = gq.trim().toLowerCase(); return !t || [g.term, g.def, g.cls, ...g.cols].join(" ").toLowerCase().includes(t); });
  const glossaryForTable = (glossary.data ?? []).filter(g => g.cols.some(c => c.startsWith(`${table}.`))).length;
  const howTo = [["1", "Take the lease.", "Only the lease holder edits a draft; published versions are read-only.", "Overview", "overview"], ["2", "Review the differences.", "New, dropped or retyped columns compared with the class.", "", ""], ["3", "Apply or edit by hand.", "Apply adds attributes and relationships; the map lets you set labels, parents and restrictions.", "Ontology", "ontology"], ["4", "Bind, then build.", "New attributes need a column in Mapping before the next build.", "Mapping", "mapping"]];
  const profileCols = profiled ? " 1.1fr .8fr 1fr" : "";
  const gridCols = `1.5fr .8fr 1.8fr .9fr${profileCols}`;

  const toggle = (name: string) => setSelected(sel => (sel.includes(name) ? sel.filter(x => x !== name) : [...sel, name]));
  const importSelected = async () => {
    if (!version || !selected.length || importing) return;
    setImporting(true);
    try { await api.importTables(domain.name, version.version, schema, selected); say(`Imported ${selected.length} table${selected.length === 1 ? "" : "s"} into the snapshot of v${version.version}`); setSelected([]); tables.reload(); }
    catch (e) { say(e instanceof Error ? e.message : String(e)); }
    finally { setImporting(false); }
  };
  const refresh = async () => {
    if (!version) return;
    try { const changes = (await api.refreshSnapshot(domain.name, version.version)).filter(c => c.missing || c.added.length || c.removed.length || c.modified.length || c.keys_changed); tables.reload(); detail.reload(); say(changes.length ? `Snapshot refreshed · ${changes.length} table${changes.length === 1 ? "" : "s"} changed: ${changes.map(c => c.table.split(".").pop()).join(", ")}` : "Snapshot refreshed · no changes"); }
    catch (e) { say(e instanceof Error ? e.message : String(e)); }
  };
  const applyDiff = (d: { column: string; action: string }) => {
    if (d.action === "Bind in Mapping" || d.action === "Open in Mapping") return go("mapping", { cls: cls ?? "" });
    setApplied(a => [...a, `${table}:${d.column}`]); say(`${d.action}: ${d.column} → ${cls || "new class"} (draft v${version?.version})`);
  };

  return (
    <>
      <div className="page-head">
        <div><h1>Metadata</h1><p>Catalog snapshot for {domain.name} v{version?.version} from {dbx ? "Databricks" : "Postgres"}. Profile tables, keep the glossary current, and push changes into the ontology.</p></div>
        <div className="actions">
          {!editable && <span className="muted small">Only the lease holder of a draft can import or refresh.</span>}
          <Button onClick={refresh} disabled={!editable}>Refresh snapshot</Button>
          <Button variant="primary" onClick={importSelected} disabled={!editable || !selected.length || importing}>{importing && <Spinner />}{selected.length ? `Import ${selected.length} selected` : "Import selected"}</Button>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "300px minmax(0,1fr)", gap: 20, alignItems: "start" }}>
        <Card flush style={{ position: "sticky", top: 0 }}>
          <div style={{ padding: 12, display: "grid", gap: 8, borderBottom: "1px solid var(--line)" }}>
            <select aria-label="Schema" className="select mono sm" style={{ fontWeight: 600, width: "100%" }} value={schema} onChange={e => { setSchema(e.target.value); setTable(""); }}>
              {[...new Set((schemas.data ?? []).map(s => s.group ?? ""))].map(g => <optgroup key={g} label={g}>{(schemas.data ?? []).filter(s => (s.group ?? "") === g).map(s => <option key={s.id} value={s.id}>{s.label}</option>)}</optgroup>)}
            </select>
            <input aria-label="Search tables" className="input sm" placeholder="Search tables" value={search} onChange={e => setSearch(e.target.value)} />
          </div>
          <div className="row between label-caps" style={{ padding: "8px 14px 4px", fontSize: 10.5, color: "var(--muted-3)" }}><span>{catList.length} tables</span><span>{catList.filter(t => t.imported).length} of {catList.length} in snapshot</span></div>
          {tables.error && <div style={{ padding: 12 }}><ErrorNotice error={tables.error} action={<span className="small">{/PERMISSION|denied|USE CATALOG/i.test(tables.error) ? "Ask the workspace admin for USE CATALOG / USE SCHEMA / SELECT on this catalog." : "Reload the page; if it persists, check that the API is running the current version."}</span>} /></div>}
          {tables.loading && <div style={{ padding: 12, display: "grid", gap: 8 }}><Skeleton h={30} /><Skeleton h={30} /><Skeleton h={30} /></div>}
          {catList.filter(t => !search || t.name.includes(search.toLowerCase())).map(t => { const on = t.name === (table || catList[0]?.name); return (
            <div key={t.name} className="row" style={{ gap: 0, borderTop: "1px solid var(--line-2)", background: on ? "var(--blue-soft)" : undefined }}>
              <input type="checkbox" aria-label={`Select ${t.name}`} checked={selected.includes(t.name)} onChange={() => toggle(t.name)} disabled={!editable || t.imported} title={t.imported ? "Already in the snapshot" : !editable ? "Only the lease holder of a draft can import" : "Select for import"} style={{ marginLeft: 12 }} />
            <a href="#" onClick={e => { e.preventDefault(); setTable(t.name); }} style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: 10, padding: "9px 14px 9px 10px", color: "var(--ink)", background: on ? "var(--blue-soft)" : "transparent", textDecoration: "none" }}>
              <Icon name="metadata" stroke={on ? BLUE : "#7A7A80"} />
              <span style={{ flex: 1, minWidth: 0 }}><span className="mono" style={{ display: "block", fontSize: 12, fontWeight: on ? 600 : 400, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.name}</span><span className="muted-2" style={{ display: "block", fontSize: 11 }}>{t.cols} cols · {t.cls ?? "no class"}</span></span>
              {t.imported && <Dot color={BLUE} title="In snapshot" />}
            </a>
            </div>); })}
        </Card>
        <Card flush>
          <div style={{ padding: "16px 20px 0", display: "flex", alignItems: "flex-start", gap: 16 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="mono" style={{ fontSize: 15, fontWeight: 500 }}>{full}</div>
              <div className="muted" style={{ fontSize: 12.5, marginTop: 3 }}>{detail.data?.comment ?? ""}</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
                <Pill size="lg" tone="outline" dot={imported ? BLUE : GREY}>{imported ? "in snapshot" : "not imported"}</Pill>
                <Pill size="lg" tone={cls ? "blue" : "outline"} dot={cls ? BLUE : GREY} onClick={() => go("ontology", { cls: cls ?? "Customer", view: "map" })}>{cls ? `class ${cls}` : "no class"}</Pill>
                {caps.profiling && <Pill size="lg" tone="outline" dot="#8FA1FF" onClick={() => setProfiled(true)}>{prof?.rows ?? "—"} rows</Pill>}
                {caps.quality && <Pill size="lg" tone="outline" dot={dqIssues.length ? ORANGE : BLUE} onClick={() => setTab("dq")}>{dqIssues.length ? `${dqIssues.length} DQ issues` : "DQ passing"}</Pill>}
              </div>
            </div>
            <div className="row" style={{ flex: "none" }}>
              {dbx && caps.profiling && <Button size="sm" variant="outline" style={{ height: 30 }} onClick={() => say(`Inferred keys for ${table}`)}>Infer keys</Button>}
              {caps.profiling && <Button size="sm" active={profiled} style={{ height: 30 }} onClick={() => { setProfiled(p => !p); if (!profiled) say(`Profiling ${table}…`); }}>{profile.loading && profiled ? <Spinner blue /> : null}{profiled ? "Hide profile" : "Profile table"}</Button>}
            </div>
          </div>
          <div style={{ padding: "12px 20px 0" }}>
            <Tabs<Tab> value={(tab as Tab) || "columns"} onChange={t => setTab(t)} items={[{ id: "columns" as Tab, label: "Columns", count: cols.length }, ...(caps.quality ? [{ id: "dq" as Tab, label: "Quick DQ", count: (dqIssues.length || false) as number | false, countStyle: { background: "#fff", color: "var(--orange-text)" } }] : []), ...(caps.ontoDiffs ? [{ id: "onto" as Tab, label: "Ontology", count: (diffsLeft.length || false) as number | false, countStyle: { background: "var(--blue-soft)", color: DARK } }] : []), ...(caps.glossary ? [{ id: "glossary" as Tab, label: "Glossary", count: (glossaryForTable || false) as number | false }] : [])]} />
          </div>

          {tab === "columns" && (
            <>
              {profiled && prof && <div style={{ display: "grid", gridTemplateColumns: "repeat(5,minmax(0,1fr))", borderBottom: "1px solid var(--line)", background: "var(--surface-2)" }}>
                {[["Rows", prof.rows, "count(*)", "var(--ink)"], ["Columns", String(cols.length), `${Object.values(prof.cols).filter(c => c[0] > 0).length} with nulls`, "var(--ink)"], ["Duplicates", prof.dup, "on inferred key", prof.dup !== "0" && prof.dup !== "—" ? "#B84F00" : BLUE], ["Freshness", prof.fresh, "last ETL write", "var(--ink)"], ["DQ", String(dqIssues.length), "columns with open issues", ORANGE]].map(([k, v, sub, color]) => <div key={k} style={{ padding: "12px 20px", borderRight: "1px solid var(--line-2)" }}><div className="label-caps" style={{ fontSize: 10.5, color: "var(--muted-2)" }}>{k}</div><div style={{ fontSize: 18, fontWeight: 800, letterSpacing: "-.02em", marginTop: 2, color }}>{v}</div><div className="muted-3" style={{ fontSize: 11 }}>{sub}</div></div>)}
              </div>}
              <div className="grid-head" style={{ gridTemplateColumns: gridCols }}><span>Column</span><span>Type</span><span>Description</span><span>Key</span>{profiled && <><span>Nulls</span><span>Distinct</span><span>DQ</span></>}</div>
              {detail.loading && <div style={{ padding: 20 }}><Skeleton h={16} /><Skeleton h={16} /><Skeleton h={16} /></div>}
              {cols.map(c => { const p = prof?.cols[c.name] ?? [0, 0]; const issue = (dq.data ?? []).find(d => d.column === c.name); const bad = issue && issue.kind !== "—"; const nullColor = p[0] > 30 ? "#B84F00" : p[0] > 0 ? "#5F5F60" : BLUE; const term = termByCol[c.name]; return (
                <div key={c.name} className="grid-row hover" style={{ gridTemplateColumns: gridCols, padding: "9px 20px" }}>
                  <span className="mono row" style={{ fontSize: 12, gap: 6, minWidth: 0 }}><span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{c.name}</span>{term && <a href="#" className="pill mini" title="Glossary term" style={{ background: "#fff", border: "1px solid var(--blue-border)", color: DARK, fontFamily: "var(--font)" }} onClick={e => { e.preventDefault(); setTab("glossary"); setGq(term); }}>{term}</a>}</span>
                  <span className="mono muted" style={{ fontSize: 11.5 }}>{c.type}</span>
                  <span style={{ color: "var(--ink-2)" }} title="Click to edit">{c.comment}</span>
                  <span>{c.key && <span className="pill" style={{ background: c.keyInferred ? "#fff" : "var(--blue-soft)", color: c.keyInferred ? "#B84F00" : DARK, border: `1px solid ${c.keyInferred ? ORANGE : "var(--blue-border)"}` }}>{c.key === "pk" ? (c.keyInferred ? "inferred key" : "primary key") : (c.keyInferred ? "inferred FK" : "foreign key")}</span>}</span>
                  {profiled && <>
                    <span className="row"><span style={{ width: 44, height: 6, borderRadius: 3, background: "var(--surface-3)", overflow: "hidden" }}><i style={{ display: "block", height: "100%", width: `${Math.max(2, p[0])}%`, background: nullColor }} /></span><span className="mono" style={{ fontSize: 11.5, color: nullColor }}>{p[0]}%</span></span>
                    <span className="mono" style={{ fontSize: 11.5 }}>{p[1].toLocaleString()}</span>
                    <a href="#" title={issue ? `Constraint kind: ${issue.kind}` : "No open violations"} className="row" style={{ fontSize: 11.5, fontWeight: 600, color: bad ? ORANGE : issue ? "#7A7A80" : BLUE, gap: 6 }} onClick={e => { e.preventDefault(); go("quality"); }}><Dot color={bad ? ORANGE : issue ? "#7A7A80" : BLUE} />{issue ? issue.count : "passing"}</a>
                  </>}
                </div>); })}
            </>
          )}

          {tab === "dq" && (
            <div style={{ padding: "16px 20px" }}>
              <div className="row between" style={{ marginBottom: 12 }}><div className="muted" style={{ fontSize: 12.5 }}>Constraints that touch <span className="mono">{table}</span> and the latest results.</div><div className="row"><Button size="sm" onClick={() => go("quality")}>Open Data quality</Button><Button size="sm" variant="primary" onClick={() => { setDqRan(true); if (!profiled) setProfiled(true); say(`Quick checks on ${table} · ${dqRows.length + (dqRan ? 0 : 2)} constraints run`); }}>Run quick checks</Button></div></div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 10, marginBottom: 14 }}>
                {[["Constraints", String(dqRows.length), "var(--ink)"], ["Open violations", String(openViolations), ORANGE], ["Last run", dqRan ? "just now" : "2 h ago", "var(--ink)"]].map(([k, v, color]) => <div key={k} style={{ padding: "12px 14px", borderRadius: 8, border: "1px solid var(--line)" }}><div className="label-caps" style={{ fontSize: 10.5, color: "var(--muted-2)" }}>{k}</div><div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.02em", color }}>{v}</div></div>)}
              </div>
              {dqRows.map((q, i) => <div key={i} style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr .9fr .7fr 1.2fr", alignItems: "center", gap: 10, padding: "9px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}><span style={{ fontWeight: 600 }}>{q.name}</span><span className="mono muted" style={{ fontSize: 11.5 }}>{q.column} · {q.kind}</span><span className="row"><Dot color={q.dot} />{q.severity}</span><span style={{ fontWeight: 700, color: q.bad ? "#B84F00" : "var(--ink)" }}>{q.count}</span><a href="#" className="mono" style={{ fontSize: 11.5 }} onClick={e => { e.preventDefault(); go("quality"); }}>{q.sample}</a></div>)}
              <div style={{ marginTop: 12, display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}><span className="muted small">Add a quick check:</span>{["unique", "min_count", "pattern", "in", "no_orphans"].map(k => <Button key={k} dashed className="mono" style={{ fontSize: 11.5 }} onClick={() => say(`Added ${k} check on ${table}`)}>{k}</Button>)}</div>
            </div>
          )}

          {tab === "onto" && (
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.3fr) minmax(0,1fr)" }}>
              <div style={{ padding: "16px 20px", borderRight: "1px solid var(--line)" }}>
                <div className="row between" style={{ marginBottom: 6 }}><h3 style={{ fontSize: 13, fontWeight: 700 }}>Differences</h3><span className="mono muted small">{cls ? `${full} → ${cls}` : "No class for this table yet"}</span></div>
                <p className="muted" style={{ fontSize: 12.5, marginBottom: 8 }}>Columns in the catalog compared with the class in draft v{version?.version}.</p>
                {(cls ? diffsLeft : [{ kind: "no class", column: table, note: "draft a class from this table's columns", action: "Create class" }]).map(d => { const warn = d.kind === "missing target"; return (
                  <div key={d.column} style={{ display: "grid", gridTemplateColumns: "auto 1fr auto", gap: 12, alignItems: "center", padding: "9px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}>
                    <span className="pill" style={{ fontSize: 10.5, fontWeight: 700, background: warn ? "#fff" : "var(--blue-soft)", color: warn ? "#B84F00" : DARK, border: `1px solid ${warn ? ORANGE : "var(--blue-border)"}` }}>{d.kind}</span>
                    <span><span className="mono" style={{ fontSize: 12 }}>{d.column}</span> <span className="muted">{d.note}</span></span>
                    <Button size="xs" style={{ height: 26, whiteSpace: "nowrap" }} onClick={() => applyDiff(d)}>{d.action}</Button>
                  </div>); })}
                {cls && diffsLeft.length === 0 && <p className="muted row" style={{ fontSize: 12.5, marginTop: 10 }}><Dot color={BLUE} size={8} />Ontology is in sync with this table.</p>}
                <div style={{ display: "flex", gap: 8, marginTop: 14, flexWrap: "wrap" }}>
                  <Button variant="primary" size="sm" style={{ height: 32 }} disabled={!!cls && diffsLeft.length === 0} onClick={() => { setApplied(a => [...a, ...diffsLeft.map(d => `${table}:${d.column}`)]); say(`Ontology updated from ${table} · ${diffsLeft.length} changes`); }}>Apply all to ontology</Button>
                  <Button size="sm" style={{ height: 32 }} onClick={() => say(`Drafting ${cls ?? "a class"} from ${table} with AI…`)}>Draft with AI from this table</Button>
                  <Button size="sm" style={{ height: 32 }} onClick={() => go("ontology", { cls: cls ?? "Customer", view: "map" })}>Open in Ontology</Button>
                </div>
              </div>
              <div style={{ padding: "16px 20px", background: "var(--surface-2)" }}>
                <h3 style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>How to update the ontology</h3>
                {howTo.map(([n, title, text, link, screen]) => <div key={n} style={{ display: "grid", gridTemplateColumns: "24px 1fr", gap: 10, padding: "8px 0", borderTop: "1px solid var(--line-3)", fontSize: 12.5, color: "var(--ink-2)" }}><span className="glyph" style={{ width: 22, height: 22, background: "var(--blue-soft)", color: DARK, fontSize: 11 }}>{n}</span><span><strong style={{ fontWeight: 600, color: "var(--ink)" }}>{title}</strong> <span>{text}</span> {link && <a href="#" style={{ fontWeight: 600 }} onClick={e => { e.preventDefault(); go(screen, screen === "mapping" ? { cls: cls ?? "Customer" } : {}); }}>{link}</a>}</span></div>)}
              </div>
            </div>
          )}

          {tab === "glossary" && (
            <div style={{ padding: "16px 20px" }}>
              <div className="row" style={{ marginBottom: 12 }}>
                <div className="search-wrap"><Icon name="search" stroke="#7A7A80" /><input aria-label="Search glossary" className="input" placeholder="Quick search terms, classes, columns…" value={gq} onChange={e => setGq(e.target.value)} /></div>
                <Button active={gScope} onClick={() => setGScope(s => !s)} style={{ whiteSpace: "nowrap" }}>This table only</Button>
                <Button variant="primary" onClick={() => say("New glossary term")}>New term</Button>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 10 }}>
                {glossaryRows.map(g => (
                  <div key={g.term} style={{ padding: "12px 14px", border: "1px solid var(--line)", borderRadius: 8 }}>
                    <div className="row between" style={{ alignItems: "baseline", gap: 10 }}><strong style={{ fontSize: 13, fontWeight: 700 }}>{g.term}</strong><span className="muted-2" style={{ fontSize: 11 }}>{g.steward}</span></div>
                    <div style={{ fontSize: 12.5, color: "var(--ink-2)", margin: "4px 0 8px" }}>{g.def}</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, fontSize: 11 }}><a href="#" className="pill" style={{ background: "var(--blue-soft)", color: DARK }} onClick={e => { e.preventDefault(); go("ontology", { cls: g.cls, view: "map" }); }}>{g.cls}</a>{g.cols.map(c => <span key={c} className="pill outline mono" style={{ color: "var(--muted)", fontWeight: 400 }}>{c}</span>)}</div>
                  </div>
                ))}
              </div>
              {glossaryRows.length === 0 && <p className="muted" style={{ fontSize: 12.5, marginTop: 8 }}>No term matches “{gq}”. <a href="#" style={{ fontWeight: 600 }} onClick={e => { e.preventDefault(); say(`Creating term “${gq}”`); }}>Create it</a>.</p>}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
