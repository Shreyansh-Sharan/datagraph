// Metadata: a workbench that fills the viewport. Left, the schema browser (every source, every
// schema, every table, searchable, tickable). Right, what is selected: a schema shows its table
// list with snapshot state and classes; a table shows its columns, keys and comments.
import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { Button, Dot, ErrorNotice, Pill, Skeleton, Spinner, Tabs } from "@/components/ui";
import { Icon } from "@/components/icons";
import { useApp, useLoad } from "@/state/app";
import { useDomain, useGo, useParam, useSetParams } from "@/state/domain";
import { tableName, type CatalogTable } from "@/api";

type Tab = "columns" | "dq" | "onto" | "glossary";
type SchemaState = { loading: boolean; error: string | null; data: CatalogTable[] | null };
const BLUE = "#2249FF", ORANGE = "#FF7000", GREY = "#B3B3B7", DARK = "#1636E0";
const SIDE_KEY = "dg.metadata.side", SIDE_MIN = 240, SIDE_MAX = 560, SIDE_DEFAULT = 320;

const full0 = (schema: string, table: string) => (schema ? `${schema}.${table}` : table);
const short = (label: string) => (label.includes(".") ? label.split(".").pop()! : label);
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const permissionHint = (error: string) => (/PERMISSION|denied|USE CATALOG/i.test(error) ? "Ask the workspace admin for USE CATALOG / USE SCHEMA / SELECT on this catalog." : "Reload the page; if it persists, check that the API is running the current version.");

/** The draggable divider between the browser and the detail pane; the width survives reloads. */
function useSideWidth(): [number, (w: number) => void] {
  const [w, setW] = useState(() => { try { const v = Number(localStorage.getItem(SIDE_KEY)); return v >= SIDE_MIN && v <= SIDE_MAX ? v : SIDE_DEFAULT; } catch { return SIDE_DEFAULT; } });
  const set = useCallback((v: number) => { const c = Math.round(Math.min(SIDE_MAX, Math.max(SIDE_MIN, v))); setW(c); try { localStorage.setItem(SIDE_KEY, String(c)); } catch { /* private mode */ } }, []);
  return [w, set];
}

export function Metadata() {
  const { api, config, say } = useApp();
  const { domain, version, editable } = useDomain();
  const go = useGo();
  const dbx = config.sourceKind === "databricks";
  const [schemaParam] = useParam("schema", "");
  const [tableParam] = useParam("table", "");
  const setParams = useSetParams();
  const [selected, setSelected] = useState<string[]>([]);
  const [importing, setImporting] = useState(false);
  const [tab, setTab] = useParam("tab", "columns");
  const [gq, setGq] = useParam("gq", "");
  const [search, setSearch] = useState("");
  const [profiled, setProfiled] = useState(false);
  const [dqRan, setDqRan] = useState(false);
  const [gScope, setGScope] = useState(false);
  const [applied, setApplied] = useState<string[]>([]);
  const [side, setSide] = useSideWidth();
  const [dragging, setDragging] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);

  const schemas = useLoad(() => api.schemas(domain.name), [domain.name]);
  const schemaIds = (schemas.data ?? []).map(s => s.id).join("|");
  const [bySchema, setBySchema] = useState<Record<string, SchemaState>>({});
  const [tick, setTick] = useState(0);
  useEffect(() => {   // every schema at once: the browser shows the whole source, not one schema at a time
    const ids = schemaIds ? schemaIds.split("|") : [];
    let alive = true;
    setBySchema(Object.fromEntries(ids.map(id => [id, { loading: true, error: null, data: null }])));
    for (const id of ids) {
      api.catalogTables(domain.name, id, version?.version)
        .then(data => { if (alive) setBySchema(b => ({ ...b, [id]: { loading: false, error: null, data } })); })
        .catch(e => { if (alive) setBySchema(b => ({ ...b, [id]: { loading: false, error: e instanceof Error ? e.message : String(e), data: null } })); });
    }
    return () => { alive = false; };
  }, [api, domain.name, schemaIds, version?.version, tick]);
  const reloadTables = () => setTick(t => t + 1);
  const anyLoading = Object.values(bySchema).some(x => x.loading);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const firstWithTables = (schemas.data ?? []).find(x => (bySchema[x.id]?.data?.length ?? 0) > 0)?.id;
  const schema = schemaParam || firstWithTables || schemas.data?.[0]?.id || "";
  const schemaInfo = (schemas.data ?? []).find(s => s.id === schema);
  const catList = bySchema[schema]?.data ?? [];
  const table = tableParam;          // empty: the pane shows the schema itself
  const keyOf = (sid: string, name: string) => `${sid}|${name}`;
  const detail = useLoad(() => table ? api.tableDetail(domain.name, schema, table) : Promise.resolve(null), [domain.name, schema, table]);
  const profile = useLoad(() => profiled && table ? api.tableProfile(domain.name, table) : Promise.resolve(null), [domain.name, table, profiled]);
  const dq = useLoad(() => table ? api.tableDq(domain.name, table) : Promise.resolve([]), [domain.name, table]);
  const glossary = useLoad(() => api.glossary(domain.name), [domain.name]);
  const diffs = useLoad(() => table ? api.ontoDiffs(domain.name, table) : Promise.resolve([]), [domain.name, table]);
  const tcls = useLoad(() => table ? api.tableClass(domain.name, full0(schema, table), version?.version) : Promise.resolve(null), [domain.name, schema, table, version?.version]);
  const caps = config.capabilities;

  const cols = detail.data?.columns ?? [];
  const full = detail.data?.fullName ?? (schema.includes(".") ? full0(schema, table) : tableName(config.sourceKind, domain.catalog, schema, table));
  const cls = tcls.data ?? null;
  const dqIssues = (dq.data ?? []).filter(d => d.kind !== "—");
  const diffsLeft = (diffs.data ?? []).filter(d => !applied.includes(`${table}:${d.column}`));
  const termByCol = Object.fromEntries((glossary.data ?? []).flatMap(g => g.cols.map(c => [c.split(".")[1], g.term])));
  const current = catList.find(t => t.name === table);
  const imported = current?.imported ?? false;
  const prof = profile.data;
  const keyCols = cols.filter(c => c.key === "pk").map(c => c.name);

  const dqRows = [
    ...dqIssues.map(d => { const n = parseInt(d.count) || 0; return { name: d.kind === "drift" ? "Target table exists" : d.kind === "pattern" ? "Country is ISO-2" : "Quantity is positive", column: d.column, kind: d.kind, severity: d.kind === "pattern" ? "warning" : "violation", dot: d.kind === "pattern" ? GREY : ORANGE, count: n || "—", bad: n > 0, sample: n ? `${cls || "Row"}/… ${n} rows` : "—" }; }),
    ...(dqRan && cols[0] ? [{ name: "Key is unique", column: cols[0].name, kind: "unique", severity: "violation", dot: ORANGE, count: prof?.dup ?? "0", bad: !!prof && prof.dup !== "0" && prof.dup !== "—", sample: "—" }, { name: "Key not null", column: cols[0].name, kind: "min_count", severity: "violation", dot: ORANGE, count: 0, bad: false, sample: "—" }] : []),
  ];
  const openViolations = dqRows.reduce((a, r) => a + (typeof r.count === "number" ? r.count : 0), 0);
  const glossaryRows = (glossary.data ?? []).filter(g => !gScope || g.cols.some(c => c.startsWith(`${table}.`))).filter(g => { const t = gq.trim().toLowerCase(); return !t || [g.term, g.def, g.cls, ...g.cols].join(" ").toLowerCase().includes(t); });
  const glossaryForTable = (glossary.data ?? []).filter(g => g.cols.some(c => c.startsWith(`${table}.`))).length;
  const howTo = [["1", "Take the lease.", "Only the lease holder edits a draft; published versions are read-only.", "Overview", "overview"], ["2", "Review the differences.", "New, dropped or retyped columns compared with the class.", "", ""], ["3", "Apply or edit by hand.", "Apply adds attributes and relationships; the map lets you set labels, parents and restrictions.", "Ontology", "ontology"], ["4", "Bind, then build.", "New attributes need a column in Mapping before the next build.", "Mapping", "mapping"]];
  const profileCols = profiled ? " 1.1fr .8fr 1fr" : "";
  const gridCols = `minmax(150px,1.2fr) minmax(90px,.7fr) minmax(0,2fr) minmax(110px,.6fr)${profileCols}`;

  // The whole source in one line under the search box.
  const loaded = Object.values(bySchema).filter(x => x.data);
  const totals = { schemas: schemas.data?.length ?? 0, tables: loaded.reduce((a, x) => a + (x.data?.length ?? 0), 0), imported: loaded.reduce((a, x) => a + (x.data?.filter(t => t.imported).length ?? 0), 0) };

  const toggle = (key: string) => setSelected(sel => (sel.includes(key) ? sel.filter(x => x !== key) : [...sel, key]));
  const toggleSchema = (sid: string, names: string[]) => setSelected(sel => { const keys = names.map(n => keyOf(sid, n)); const all = keys.every(k => sel.includes(k)); return all ? sel.filter(k => !keys.includes(k)) : [...new Set([...sel, ...keys])]; });
  const openSchema = (sid: string) => { setExpanded(x => ({ ...x, [sid]: true })); setParams({ schema: sid, table: "" }); };
  const openTable = (sid: string, name: string) => setParams({ schema: sid, table: name });
  const importSelected = async () => {
    if (!version || !selected.length || importing) return;
    setImporting(true);
    try {
      const groups: Record<string, string[]> = {};
      for (const k of selected) { const [sid, name] = k.split("|"); (groups[sid] ||= []).push(name); }
      for (const [sid, names] of Object.entries(groups)) await api.importTables(domain.name, version.version, sid, names);
      say(`Imported ${plural(selected.length, "table")} into the snapshot of v${version.version}`); setSelected([]); reloadTables();
    }
    catch (e) { say(e instanceof Error ? e.message : String(e)); }
    finally { setImporting(false); }
  };
  const refresh = async () => {
    if (!version) return;
    try { const changes = (await api.refreshSnapshot(domain.name, version.version)).filter(c => c.missing || c.added.length || c.removed.length || c.modified.length || c.keys_changed); reloadTables(); detail.reload(); say(changes.length ? `Snapshot refreshed · ${plural(changes.length, "table")} changed: ${changes.map(c => c.table.split(".").pop()).join(", ")}` : "Snapshot refreshed · no changes"); }
    catch (e) { say(e instanceof Error ? e.message : String(e)); }
  };
  const applyDiff = (d: { column: string; action: string }) => {
    if (d.action === "Bind in Mapping" || d.action === "Open in Mapping") return go("mapping", { cls: cls ?? "" });
    setApplied(a => [...a, `${table}:${d.column}`]); say(`${d.action}: ${d.column} → ${cls || "new class"} (draft v${version?.version})`);
  };

  // Divider: pointer drag, or arrow keys when it has focus.
  const onHandleDown = (e: React.PointerEvent<HTMLDivElement>) => {
    const left = bodyRef.current?.getBoundingClientRect().left ?? 0;
    e.currentTarget.setPointerCapture(e.pointerId); setDragging(true);
    const move = (ev: PointerEvent) => setSide(ev.clientX - left);
    const up = () => { setDragging(false); window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
  };
  const onHandleKey = (e: React.KeyboardEvent) => { if (e.key === "ArrowLeft") { e.preventDefault(); setSide(side - 16); } if (e.key === "ArrowRight") { e.preventDefault(); setSide(side + 16); } };

  const q = search.trim().toLowerCase();
  const sourceName = dbx ? "Databricks" : "Postgres";

  return (
    <div className="bench">
      <div className="page-head">
        <div><h1>Metadata</h1><p>Tables the {sourceName} source offers for {domain.name} v{version?.version}. Tick tables and import them into the snapshot; the ontology and mapping read from there.</p></div>
        <div className="actions">
          {!editable && <span className="muted small">Only the lease holder of a draft can import or refresh.</span>}
          <Button onClick={refresh} disabled={!editable}>Refresh snapshot</Button>
          <Button variant="primary" onClick={importSelected} disabled={!editable || !selected.length || importing}>{importing && <Spinner />}{selected.length ? `Import ${selected.length} selected` : "Import selected"}</Button>
        </div>
      </div>

      <div ref={bodyRef} className={`bench-body ${dragging ? "dragging" : ""}`} style={{ "--side": `${side}px` } as CSSProperties}>
        <aside className="bench-side" aria-label="Schema browser">
          <div className="bench-side-head">
            <div className="search-wrap"><Icon name="search" stroke="#7A7A80" /><input aria-label="Search tables" className="input sm" placeholder="Search tables in every schema" value={search} onChange={e => setSearch(e.target.value)} /></div>
            <div className="bench-sum">{schemas.loading ? "Reading the source…" : anyLoading ? `Reading ${plural(totals.schemas, "schema")}…` : totals.schemas ? `${plural(totals.schemas, "schema")} · ${plural(totals.tables, "table")} · ${totals.imported} in snapshot` : "No schema configured"}</div>
          </div>
          <div className="bench-scroll">
            {schemas.loading && <div style={{ padding: 12, display: "grid", gap: 8 }}><Skeleton h={28} /><Skeleton h={28} /><Skeleton h={28} /></div>}
            {schemas.data?.length === 0 && <p className="muted small" style={{ padding: 12 }}>No schema on this domain yet: pick the source's schemas on the Configure screen.</p>}
            <div role="tree" aria-label="Schemas and tables">
              {(schemas.data ?? []).map((sc, i) => {
                const st = bySchema[sc.id]; const all = st?.data ?? [];
                const rows = q ? all.filter(t => t.name.toLowerCase().includes(q)) : all;
                if (q && rows.length === 0) return null;
                const open = expanded[sc.id] ?? true; const openable = all.filter(t => !t.imported).map(t => t.name);
                const allPicked = openable.length > 0 && openable.every(n => selected.includes(keyOf(sc.id, n)));
                const prevGroup = i > 0 ? schemas.data?.[i - 1]?.group : undefined;
                const onSchema = sc.id === schema && !table;
                return (
                  <div key={sc.id} role="treeitem" aria-expanded={open} aria-label={sc.label}>
                    {sc.group && sc.group !== prevGroup && <div className="tree-group">{sc.group}</div>}
                    <div className={`tree-schema ${onSchema ? "on" : ""}`}>
                      <button type="button" className="chip-act" aria-label={`${open ? "Collapse" : "Expand"} ${sc.label}`} onClick={() => setExpanded(x => ({ ...x, [sc.id]: !open }))}>{open ? "▾" : "▸"}</button>
                      <input type="checkbox" aria-label={`Select all in ${sc.label}`} checked={allPicked} disabled={!editable || openable.length === 0} title={openable.length ? `Select the ${plural(openable.length, "table")} not yet in the snapshot` : "Every table is in the snapshot"} onChange={() => toggleSchema(sc.id, openable)} />
                      <a href="#" className="name" title={sc.label} onClick={e => { e.preventDefault(); openSchema(sc.id); }}>{short(sc.label)}</a>
                      <span className="n">{st?.loading ? <Spinner blue /> : st?.error ? "failed" : `${all.filter(t => t.imported).length} of ${all.length} in snapshot`}</span>
                    </div>
                    {st?.error && open && <div style={{ padding: "0 12px 10px" }}><ErrorNotice error={st.error} action={<span className="small">{permissionHint(st.error)}</span>} /></div>}
                    {open && rows.map(t => { const on = sc.id === schema && t.name === table; const k = keyOf(sc.id, t.name); return (
                      <div key={k} role="treeitem" aria-selected={on} className={`tree-table ${on ? "on" : ""}`}>
                        <input type="checkbox" aria-label={`Select ${t.name}`} checked={selected.includes(k)} onChange={() => toggle(k)} disabled={!editable || t.imported} title={t.imported ? "Already in the snapshot" : !editable ? "Only the lease holder of a draft can import" : "Select for import"} />
                        <a href="#" className="tree-link" onClick={e => { e.preventDefault(); openTable(sc.id, t.name); }}>
                          <span className="name" title={t.name}>{t.name}</span>
                          {t.cls && <span className="cls" title={`Class ${t.cls}`}>{t.cls}</span>}
                          <span className="n" title={`${t.cols} columns`}>{t.cols}</span>
                          <Dot color={t.imported ? BLUE : "transparent"} title={t.imported ? "In snapshot" : undefined} style={{ border: t.imported ? undefined : `1px solid ${GREY}` }} />
                        </a>
                      </div>); })}
                    {open && !st?.loading && !st?.error && all.length === 0 && <p className="muted-2 xs" style={{ padding: "2px 14px 8px 32px" }}>No tables.</p>}
                  </div>);
              })}
            </div>
          </div>
        </aside>

        <div className={`bench-handle ${dragging ? "on" : ""}`} role="separator" aria-orientation="vertical" aria-label="Resize the schema browser" aria-valuemin={SIDE_MIN} aria-valuemax={SIDE_MAX} aria-valuenow={side} tabIndex={0} onPointerDown={onHandleDown} onKeyDown={onHandleKey} />

        <section className="bench-main" aria-label={table ? `Table ${table}` : schemaInfo ? `Schema ${schemaInfo.label}` : "Details"}>
          {!table && (schemas.loading || (!schemaInfo && anyLoading)) && <div style={{ padding: 24 }}><Skeleton h={22} w={260} /><Skeleton h={14} w={360} style={{ marginTop: 10 }} /><Skeleton h={120} style={{ marginTop: 24 }} /></div>}

          {!table && schemaInfo && (() => {
            const st = bySchema[schema]; const all = st?.data ?? [];
            const withClass = all.filter(t => t.cls).length; const inSnap = all.filter(t => t.imported).length;
            const openable = all.filter(t => !t.imported).map(t => t.name);
            const allPicked = openable.length > 0 && openable.every(n => selected.includes(keyOf(schema, n)));
            return (
              <>
                <header className="detail-head">
                  <div className="detail-title">
                    {schemaInfo.group && <div className="detail-crumb">{schemaInfo.group}</div>}
                    <h2 className="mono">{schemaInfo.label}</h2>
                    <p className="muted">{st?.loading ? "Reading tables…" : st?.error ? "Could not read this schema." : `${plural(all.length, "table")} · ${inSnap} in snapshot · ${withClass} with a class`}</p>
                  </div>
                  <div className="detail-aside">
                    <Button size="sm" disabled={!editable || openable.length === 0} onClick={() => toggleSchema(schema, openable)}>{allPicked ? "Clear selection" : openable.length ? `Select ${plural(openable.length, "table")} not in snapshot` : "All tables in snapshot"}</Button>
                  </div>
                </header>
                {st?.error && <div style={{ padding: "0 24px 24px" }}><ErrorNotice error={st.error} action={<span className="small">{permissionHint(st.error)}</span>} /></div>}
                {st?.loading && <div style={{ padding: "0 24px" }}><Skeleton h={32} /><Skeleton h={32} style={{ marginTop: 6 }} /><Skeleton h={32} style={{ marginTop: 6 }} /></div>}
                {st?.data && all.length === 0 && <p className="muted" style={{ padding: "0 24px" }}>This schema has no tables, or the connection cannot list them.</p>}
                {st?.data && all.length > 0 && (
                  <table className="dense" aria-label={`Tables in ${schemaInfo.label}`}>
                    <thead><tr><th style={{ width: 36 }} /><th>Table</th><th style={{ width: 90, textAlign: "right" }}>Columns</th><th style={{ width: 150 }}>Snapshot</th><th>Class</th></tr></thead>
                    <tbody>
                      {all.map(t => { const k = keyOf(schema, t.name); return (
                        <tr key={t.name}>
                          <td><input type="checkbox" aria-label={`Select ${schema}.${t.name}`} checked={selected.includes(k)} onChange={() => toggle(k)} disabled={!editable || t.imported} title={t.imported ? "Already in the snapshot" : !editable ? "Only the lease holder of a draft can import" : "Select for import"} /></td>
                          <td><a href="#" className="mono" style={{ color: "var(--ink)", fontWeight: 600 }} onClick={e => { e.preventDefault(); openTable(schema, t.name); }}>{t.name}</a></td>
                          <td className="mono" style={{ textAlign: "right", color: "var(--ink-2)" }}>{t.cols}</td>
                          <td><span className="row" style={{ gap: 6, color: t.imported ? "var(--ink)" : "var(--muted-2)" }}><Dot color={t.imported ? BLUE : GREY} />{t.imported ? "in snapshot" : "not imported"}</span></td>
                          <td>{t.cls ? <a href="#" style={{ fontWeight: 600 }} onClick={e => { e.preventDefault(); go("ontology", { cls: t.cls!, view: "map" }); }}>{t.cls}</a> : <span className="muted-3">—</span>}</td>
                        </tr>); })}
                    </tbody>
                  </table>
                )}
              </>
            );
          })()}

          {table && (
            <>
              <header className="detail-head">
                <div className="detail-title">
                  <div className="detail-crumb"><a href="#" onClick={e => { e.preventDefault(); openSchema(schema); }}>{schemaInfo?.label ?? schema}</a></div>
                  <h2 className="mono">{table}</h2>
                  {detail.loading ? <Skeleton h={14} w={320} style={{ marginTop: 6 }} /> : <p className="muted">{detail.data?.comment || "No description in the catalog."}</p>}
                  <div className="detail-facts">
                    <Pill size="lg" tone="outline" dot={imported ? BLUE : GREY}>{imported ? "in snapshot" : "not imported"}</Pill>
                    <Pill size="lg" tone={cls ? "blue" : "outline"} dot={cls ? BLUE : GREY} onClick={cls ? () => go("ontology", { cls, view: "map" }) : undefined}>{cls ? `class ${cls}` : "no class"}</Pill>
                    {detail.data && <Pill size="lg" tone="outline">{plural(cols.length, "column")}</Pill>}
                    {keyCols.length > 0 && <Pill size="lg" tone="outline" title="Primary key">key {keyCols.join(", ")}</Pill>}
                    {caps.profiling && <Pill size="lg" tone="outline" dot="#8FA1FF" onClick={() => setProfiled(true)}>{prof?.rows ?? "—"} rows</Pill>}
                    {caps.quality && <Pill size="lg" tone="outline" dot={dqIssues.length ? ORANGE : BLUE} onClick={() => setTab("dq")}>{dqIssues.length ? `${dqIssues.length} DQ issues` : "DQ passing"}</Pill>}
                  </div>
                </div>
                <div className="detail-aside">
                  <span className="mono muted-2 xs fullname" title="Full name in the source">{full}</span>
                  {dbx && caps.profiling && <Button size="sm" variant="outline" onClick={() => say(`Inferred keys for ${table}`)}>Infer keys</Button>}
                  {caps.profiling && <Button size="sm" active={profiled} onClick={() => { setProfiled(p => !p); if (!profiled) say(`Profiling ${table}…`); }}>{profile.loading && profiled ? <Spinner blue /> : null}{profiled ? "Hide profile" : "Profile table"}</Button>}
                </div>
              </header>
              <Tabs<Tab> pad value={(tab as Tab) || "columns"} onChange={t => setTab(t)} items={[{ id: "columns" as Tab, label: "Columns", count: detail.data ? cols.length : false }, ...(caps.quality ? [{ id: "dq" as Tab, label: "Quick DQ", count: (dqIssues.length || false) as number | false, countStyle: { background: "#fff", color: "var(--orange-text)" } }] : []), ...(caps.ontoDiffs ? [{ id: "onto" as Tab, label: "Ontology", count: (diffsLeft.length || false) as number | false, countStyle: { background: "var(--blue-soft)", color: DARK } }] : []), ...(caps.glossary ? [{ id: "glossary" as Tab, label: "Glossary", count: (glossaryForTable || false) as number | false }] : [])]} />

              {tab === "columns" && (
                <>
                  {profiled && prof && <div style={{ display: "grid", gridTemplateColumns: "repeat(5,minmax(0,1fr))", borderBottom: "1px solid var(--line)", background: "var(--surface-2)" }}>
                    {[["Rows", prof.rows, "count(*)", "var(--ink)"], ["Columns", String(cols.length), `${Object.values(prof.cols).filter(c => c[0] > 0).length} with nulls`, "var(--ink)"], ["Duplicates", prof.dup, "on inferred key", prof.dup !== "0" && prof.dup !== "—" ? "#B84F00" : BLUE], ["Freshness", prof.fresh, "last ETL write", "var(--ink)"], ["DQ", String(dqIssues.length), "columns with open issues", ORANGE]].map(([k, v, sub, color]) => <div key={k} style={{ padding: "12px 24px", borderRight: "1px solid var(--line-2)" }}><div className="label-caps" style={{ fontSize: 10.5, color: "var(--muted-2)" }}>{k}</div><div style={{ fontSize: 18, fontWeight: 800, letterSpacing: "-.02em", marginTop: 2, color }}>{v}</div><div className="muted-3" style={{ fontSize: 11 }}>{sub}</div></div>)}
                  </div>}
                  <div className="grid-head" style={{ gridTemplateColumns: gridCols, padding: "8px 24px" }}><span>Column</span><span>Type</span><span>Description</span><span>Key</span>{profiled && <><span>Nulls</span><span>Distinct</span><span>DQ</span></>}</div>
                  {detail.loading && <div style={{ padding: "12px 24px", display: "grid", gap: 10 }}><Skeleton h={16} /><Skeleton h={16} /><Skeleton h={16} /><Skeleton h={16} /></div>}
                  {detail.error && <div style={{ padding: "0 24px" }}><ErrorNotice error={detail.error} action={<span className="small">{permissionHint(detail.error)}</span>} /></div>}
                  {cols.map(c => { const p = prof?.cols[c.name] ?? [0, 0]; const issue = (dq.data ?? []).find(d => d.column === c.name); const bad = issue && issue.kind !== "—"; const nullColor = p[0] > 30 ? "#B84F00" : p[0] > 0 ? "#5F5F60" : BLUE; const term = termByCol[c.name]; return (
                    <div key={c.name} className="grid-row hover" style={{ gridTemplateColumns: gridCols, padding: "8px 24px", alignItems: "baseline" }}>
                      <span className="mono row" style={{ fontSize: 12, gap: 6, minWidth: 0 }}><span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{c.name}</span>{term && <a href="#" className="pill mini" title="Glossary term" style={{ background: "#fff", border: "1px solid var(--blue-border)", color: DARK, fontFamily: "var(--font)" }} onClick={e => { e.preventDefault(); setTab("glossary"); setGq(term); }}>{term}</a>}</span>
                      <span className="mono muted" style={{ fontSize: 11.5 }}>{c.type}</span>
                      <span style={{ color: c.comment ? "var(--ink-2)" : "var(--muted-3)", whiteSpace: "normal" }}>{c.comment || "—"}</span>
                      <span>{c.key && <span className="pill" style={{ background: c.keyInferred ? "#fff" : "var(--blue-soft)", color: c.keyInferred ? "#B84F00" : DARK, border: `1px solid ${c.keyInferred ? ORANGE : "var(--blue-border)"}` }}>{c.key === "pk" ? (c.keyInferred ? "inferred key" : "primary key") : (c.keyInferred ? "inferred FK" : "foreign key")}</span>}</span>
                      {profiled && <>
                        <span className="row"><span style={{ width: 44, height: 6, borderRadius: 3, background: "var(--surface-3)", overflow: "hidden" }}><i style={{ display: "block", height: "100%", width: `${Math.max(2, p[0])}%`, background: nullColor }} /></span><span className="mono" style={{ fontSize: 11.5, color: nullColor }}>{p[0]}%</span></span>
                        <span className="mono" style={{ fontSize: 11.5 }}>{p[1].toLocaleString()}</span>
                        <a href="#" title={issue ? `Constraint kind: ${issue.kind}` : "No open violations"} className="row" style={{ fontSize: 11.5, fontWeight: 600, color: bad ? ORANGE : issue ? "#7A7A80" : BLUE, gap: 6 }} onClick={e => { e.preventDefault(); go("quality"); }}><Dot color={bad ? ORANGE : issue ? "#7A7A80" : BLUE} />{issue ? issue.count : "passing"}</a>
                      </>}
                    </div>); })}
                  {detail.data && cols.length === 0 && <p className="muted" style={{ padding: "16px 24px" }}>The catalog reports no columns for this table.</p>}
                </>
              )}

              {tab === "dq" && (
                <div style={{ padding: "16px 24px" }}>
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
                  <div style={{ padding: "16px 24px", borderRight: "1px solid var(--line)" }}>
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
                      <Button size="sm" style={{ height: 32 }} disabled={!editable} onClick={async () => { try { const r = await api.draftOntology(domain.name, version!.version, { ai: true, tables: [full] }); say(`Drafted ${r.classes} classes from ${table}`); go("ontology"); } catch (e) { say(e instanceof Error ? e.message : String(e)); } }}>Draft with AI from this table</Button>
                      <Button size="sm" style={{ height: 32 }} onClick={() => go("ontology", { cls: cls ?? "Customer", view: "map" })}>Open in Ontology</Button>
                    </div>
                  </div>
                  <div style={{ padding: "16px 24px", background: "var(--surface-2)" }}>
                    <h3 style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>How to update the ontology</h3>
                    {howTo.map(([n, title, text, link, screen]) => <div key={n} style={{ display: "grid", gridTemplateColumns: "24px 1fr", gap: 10, padding: "8px 0", borderTop: "1px solid var(--line-3)", fontSize: 12.5, color: "var(--ink-2)" }}><span className="glyph" style={{ width: 22, height: 22, background: "var(--blue-soft)", color: DARK, fontSize: 11 }}>{n}</span><span><strong style={{ fontWeight: 600, color: "var(--ink)" }}>{title}</strong> <span>{text}</span> {link && <a href="#" style={{ fontWeight: 600 }} onClick={e => { e.preventDefault(); go(screen, screen === "mapping" ? { cls: cls ?? "Customer" } : {}); }}>{link}</a>}</span></div>)}
                  </div>
                </div>
              )}

              {tab === "glossary" && (
                <div style={{ padding: "16px 24px" }}>
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
            </>
          )}
        </section>
      </div>
    </div>
  );
}
