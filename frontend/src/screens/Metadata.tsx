// Metadata: the source at a glance (tiles), a rail of filters, one list of every table of every
// schema (grouped, searchable, tickable) and a detail column for the chosen table: its card,
// its columns, and whatever the deployment offers (profile, glossary, data quality).
import { useEffect, useMemo, useRef, useState } from "react";
import { Button, Dot, ErrorNotice, Skeleton, Spinner, Tabs } from "@/components/ui";
import { Icon } from "@/components/icons";
import { useApp, useLoad } from "@/state/app";
import { useDomain, useGo, useParam, useSetParams } from "@/state/domain";
import { tableName, type CatalogTable } from "@/api";

type Tab = "columns" | "profile" | "glossary" | "dq";
type Status = "all" | "in" | "out" | "unmapped";
type SchemaState = { loading: boolean; error: string | null; data: CatalogTable[] | null };
type Row = { sid: string; label: string; short: string; t: CatalogTable; key: string };
const BLUE = "#2249FF", ORANGE = "#FF7000", GREY = "#B3B3B7";

const full0 = (schema: string, table: string) => (schema ? `${schema}.${table}` : table);
const short = (label: string) => (label.includes(".") ? label.split(".").pop()! : label);
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const permissionHint = (error: string) => (/PERMISSION|denied|USE CATALOG/i.test(error) ? "Ask the workspace admin for USE CATALOG / USE SCHEMA / SELECT on this catalog." : "Reload the page; if it persists, check that the API is running the current version.");
const typing = (el: EventTarget | null) => el instanceof HTMLElement && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);

export function Metadata() {
  const { api, config, say } = useApp();
  const { domain, version, editable } = useDomain();
  const go = useGo();
  const dbx = config.sourceKind === "databricks";
  const caps = config.capabilities;
  const [schemaParam] = useParam("schema", "");
  const [tableParam] = useParam("table", "");
  const setParams = useSetParams();
  const [tab, setTab] = useParam("tab", "columns");
  const [gq, setGq] = useParam("gq", "");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<Status>("all");
  const [only, setOnly] = useState<string[]>([]);          // schema ids ticked in the rail; none = every schema
  const [selected, setSelected] = useState<string[]>([]);  // `${schemaId}|${table}` keys ticked for import
  const [lastTick, setLastTick] = useState<string | null>(null);
  const [busy, setBusy] = useState<"import" | "one" | null>(null);
  const [profiled, setProfiled] = useState(false);
  const [dqRan, setDqRan] = useState(false);
  const [gScope, setGScope] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  // -- the source: every schema, every table, loaded at once ------------------------------------
  const schemas = useLoad(() => api.schemas(domain.name), [domain.name]);
  const schemaIds = (schemas.data ?? []).map(s => s.id).join("|");
  const [bySchema, setBySchema] = useState<Record<string, SchemaState>>({});
  const [tick, setTick] = useState(0);
  useEffect(() => {
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
  const reload = () => setTick(t => t + 1);
  const anyLoading = schemas.loading || Object.values(bySchema).some(x => x.loading);

  const all: Row[] = useMemo(() => (schemas.data ?? []).flatMap(sc => (bySchema[sc.id]?.data ?? []).map(t => ({ sid: sc.id, label: sc.label, short: short(sc.label), t, key: `${sc.id}|${t.name}` }))), [schemas.data, bySchema]);
  const counts = { all: all.length, in: all.filter(r => r.t.imported).length, out: all.filter(r => !r.t.imported).length, unmapped: all.filter(r => !r.t.cls).length };
  const q = search.trim().toLowerCase();
  const visible = all.filter(r => (status === "all" || (status === "in" && r.t.imported) || (status === "out" && !r.t.imported) || (status === "unmapped" && !r.t.cls))
    && (only.length === 0 || only.includes(r.sid))
    && (!q || r.t.name.toLowerCase().includes(q) || r.label.toLowerCase().includes(q) || (r.t.cls ?? "").toLowerCase().includes(q)));
  const groups = (schemas.data ?? []).map(sc => ({ sc, rows: visible.filter(r => r.sid === sc.id), all: bySchema[sc.id]?.data ?? [], st: bySchema[sc.id] })).filter(g => g.rows.length || (!q && status === "all" && only.length === 0));

  // -- the chosen table -------------------------------------------------------------------------
  const named = tableParam ? all.find(r => r.sid === (schemaParam || r.sid) && r.t.name === tableParam) ?? null : null;
  const current = named ?? (tableParam && anyLoading ? null : visible[0] ?? all[0] ?? null);   // the named table may still be loading: do not jump to another one meanwhile
  const schema = current?.sid ?? schemaParam;
  const table = current?.t.name ?? "";
  const pick = (r: Row) => setParams({ schema: r.sid, table: r.t.name });
  const detail = useLoad(() => table ? api.tableDetail(domain.name, schema, table) : Promise.resolve(null), [domain.name, schema, table]);
  const profile = useLoad(() => profiled && table ? api.tableProfile(domain.name, table) : Promise.resolve(null), [domain.name, table, profiled]);
  const dq = useLoad(() => caps.quality && table ? api.tableDq(domain.name, table) : Promise.resolve([]), [domain.name, table, caps.quality]);
  const glossary = useLoad(() => caps.glossary ? api.glossary(domain.name) : Promise.resolve([]), [domain.name, caps.glossary]);
  const tcls = useLoad(() => table ? api.tableClass(domain.name, full0(schema, table), version?.version) : Promise.resolve(null), [domain.name, schema, table, version?.version]);
  const cols = detail.data?.columns ?? [];
  const cls = tcls.data ?? current?.t.cls ?? null;
  const full = detail.data?.fullName ?? (schema.includes(".") ? full0(schema, table) : tableName(config.sourceKind, domain.catalog, schema, table));
  const keyCols = cols.filter(c => c.key === "pk").map(c => c.name);
  const prof = profile.data;
  const dqIssues = (dq.data ?? []).filter(d => d.kind !== "—");
  const dqScore = cols.length ? Math.round(100 * (1 - dqIssues.length / cols.length)) : null;
  const termByCol = Object.fromEntries((glossary.data ?? []).flatMap(g => g.cols.map(c => [c.split(".")[1], g.term])));
  const glossaryRows = (glossary.data ?? []).filter(g => !gScope || g.cols.some(c => c.startsWith(`${table}.`))).filter(g => { const t = gq.trim().toLowerCase(); return !t || [g.term, g.def, g.cls, ...g.cols].join(" ").toLowerCase().includes(t); });
  const glossaryForTable = (glossary.data ?? []).filter(g => g.cols.some(c => c.startsWith(`${table}.`))).length;
  const dqRows = [
    ...dqIssues.map(d => { const n = parseInt(d.count) || 0; return { name: d.kind === "drift" ? "Target table exists" : d.kind === "pattern" ? "Country is ISO-2" : "Quantity is positive", column: d.column, kind: d.kind, severity: d.kind === "pattern" ? "warning" : "violation", dot: d.kind === "pattern" ? GREY : ORANGE, count: n || "—", bad: n > 0 }; }),
    ...(dqRan && cols[0] ? [{ name: "Key is unique", column: cols[0].name, kind: "unique", severity: "violation", dot: ORANGE, count: prof?.dup ?? "0", bad: !!prof && prof.dup !== "0" && prof.dup !== "—" }, { name: "Key not null", column: cols[0].name, kind: "min_count", severity: "violation", dot: ORANGE, count: 0, bad: false }] : []),
  ];

  // -- ticking and the snapshot -----------------------------------------------------------------
  const importable = (r: Row) => editable && !r.t.imported;
  const toggle = (r: Row, range = false) => {
    if (!importable(r)) return;
    setSelected(sel => {
      if (range && lastTick) {
        const a = visible.findIndex(x => x.key === lastTick), b = visible.findIndex(x => x.key === r.key);
        if (a >= 0 && b >= 0) { const span = visible.slice(Math.min(a, b), Math.max(a, b) + 1).filter(importable).map(x => x.key); return [...new Set([...sel, ...span])]; }
      }
      return sel.includes(r.key) ? sel.filter(k => k !== r.key) : [...sel, r.key];
    });
    setLastTick(r.key);
  };
  const toggleSchema = (sid: string) => {
    const keys = all.filter(r => r.sid === sid && importable(r)).map(r => r.key);
    setSelected(sel => keys.every(k => sel.includes(k)) ? sel.filter(k => !keys.includes(k)) : [...new Set([...sel, ...keys])]);
  };
  const importKeys = async (keys: string[], done: (n: number) => string) => {
    if (!version || !keys.length || busy) return;
    setBusy(keys.length === 1 && keys[0] === current?.key && !selected.includes(keys[0]) ? "one" : "import");
    try {
      const groupsBySchema: Record<string, string[]> = {};
      for (const k of keys) { const [sid, name] = k.split("|"); (groupsBySchema[sid] ||= []).push(name); }
      for (const [sid, names] of Object.entries(groupsBySchema)) await api.importTables(domain.name, version.version, sid, names);
      say(done(keys.length)); setSelected(sel => sel.filter(k => !keys.includes(k))); reload();
    } catch (e) { say(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(null); }
  };
  const importSelected = () => importKeys(selected, n => `Imported ${plural(n, "table")} into the snapshot of v${version?.version}`);
  const addCurrent = () => current && importKeys([current.key], () => `Added ${current.t.name} to the snapshot of v${version?.version}`);
  const removeCurrent = async () => {
    if (!version || !current || busy) return;
    setBusy("one");
    try { await api.removeTable(domain.name, version.version, current.t.held ?? `${current.sid}.${current.t.name}`); say(`${current.t.name} removed from the snapshot of v${version.version}`); reload(); detail.reload(); }
    catch (e) { say(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(null); }
  };
  const refresh = async () => {
    if (!version) return;
    try { const changes = (await api.refreshSnapshot(domain.name, version.version)).filter(c => c.missing || c.added.length || c.removed.length || c.modified.length || c.keys_changed); reload(); detail.reload(); say(changes.length ? `Snapshot refreshed · ${plural(changes.length, "table")} changed: ${changes.map(c => c.table.split(".").pop()).join(", ")}` : "Snapshot refreshed · no changes"); }
    catch (e) { say(e instanceof Error ? e.message : String(e)); }
  };

  // -- keyboard: / searches, arrows walk the visible rows, space ticks the current one ----------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && typing(e.target)) { (e.target as HTMLElement).blur(); return; }
      if (typing(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "/") { e.preventDefault(); searchRef.current?.focus(); return; }
      const i = current ? visible.findIndex(r => r.key === current.key) : -1;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const next = visible[Math.min(visible.length - 1, Math.max(0, i + (e.key === "ArrowDown" ? 1 : -1)))];
        if (next) pick(next);
      }
      if (e.key === " " && current) { e.preventDefault(); toggle(current); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const source = dbx ? "databricks" : "postgres";
  const tiles: [string, string, number | null, string][] = [["Schemas in the source", "Schemas", schemas.data?.length ?? null, BLUE], ["Tables in the source", "Tables", anyLoading ? null : counts.all, BLUE], ["Tables in the snapshot", "In snapshot", anyLoading ? null : counts.in, ORANGE]];
  const tabs = [{ id: "columns" as Tab, label: "Columns", count: detail.data ? cols.length : false as const }, ...(caps.profiling ? [{ id: "profile" as Tab, label: "Profile" }] : []), ...(caps.glossary ? [{ id: "glossary" as Tab, label: "Glossary", count: (glossaryForTable || false) as number | false }] : []), ...(caps.quality ? [{ id: "dq" as Tab, label: "Data quality", count: dqScore != null ? `${dqScore}%` : false as const }] : [])];

  return (
    <div className="meta">
      <div className="meta-head">
        <div className="page-head"><div><h1>Metadata</h1><p>{source} · {domain.name} v{version?.version}</p></div></div>
        <div className="meta-tiles">
          {tiles.map(([aria, k, v, color]) => <div key={k} className="tile" aria-label={aria}><span className="k">{k}<Dot color={color} /></span><b>{v == null ? <Skeleton h={22} w={40} style={{ margin: "6px 0 8px" }} /> : v}</b><i /></div>)}
        </div>
        <div className="meta-actions">
          {!editable && <span className="muted small">Only the lease holder of a draft can import or refresh.</span>}
          <Button onClick={refresh} disabled={!editable}>Refresh snapshot</Button>
          <Button variant="primary" onClick={importSelected} disabled={!editable || !selected.length || !!busy}>{busy === "import" && <Spinner />}{selected.length ? `Import ${selected.length} selected` : "Import selected"}</Button>
        </div>
      </div>

      <div className="meta-body">
        <nav className="meta-rail" aria-label="Filters">
          <div className="rail-h">Status</div>
          {([["all", "All tables"], ["in", "In snapshot"], ["out", "Not imported"], ["unmapped", "Unmapped"]] as [Status, string][]).map(([id, label]) => (
            <button key={id} type="button" className="rail-btn" aria-pressed={status === id} onClick={() => setStatus(id)}>{label}<span className="n">{anyLoading ? "…" : counts[id]}</span></button>))}
          <div className="rail-h">Schemas</div>
          {schemas.loading && !schemas.data && <div style={{ padding: "0 8px", display: "grid", gap: 8 }}><Skeleton h={22} /><Skeleton h={22} /></div>}
          {schemas.data?.length === 0 && <p className="muted small" style={{ padding: "0 8px" }}>No schema on this domain yet: pick the source's schemas on the Configure screen.</p>}
          {(schemas.data ?? []).map(sc => { const st = bySchema[sc.id]; const n = st?.data?.length ?? 0; const inSnap = st?.data?.filter(t => t.imported).length ?? 0; return (
            <label key={sc.id} className="rail-schema" title={sc.group ? `${sc.group} · ${sc.label}` : sc.label}>
              <span className="top"><input type="checkbox" aria-label={`Only ${short(sc.label)}`} checked={only.includes(sc.id)} onChange={() => setOnly(o => o.includes(sc.id) ? o.filter(x => x !== sc.id) : [...o, sc.id])} /><span className="name">{short(sc.label)}</span><span className="n">{st?.loading ? <Spinner blue /> : st?.error ? "failed" : `${inSnap}/${n}`}</span></span>
              <span className="bar"><i style={{ width: n ? `${Math.round(100 * inSnap / n)}%` : 0 }} /></span>
            </label>); })}
          <div className="shortcuts">
            <div className="rail-h">Shortcuts</div>
            <div><span className="kbd">/</span>Search</div><div><span className="kbd">↑ ↓</span>Move</div><div><span className="kbd">Space</span>Tick</div><div><span className="kbd">⇧ click</span>Range</div>
          </div>
        </nav>

        <section className="meta-list" aria-label="Tables of the source">
          <div className="meta-search">
            <div className="search-wrap"><Icon name="search" stroke="#7A7A80" /><input ref={searchRef} aria-label="Search tables" className="input" placeholder="Search tables, schemas or ontology classes" value={search} onChange={e => setSearch(e.target.value)} /></div>
            <span className="count">{anyLoading ? "Reading the source…" : `${visible.length} of ${counts.all} tables`}</span>
          </div>
          <div className="meta-scroll">
            <table className="tables" aria-label="Tables">
              <colgroup><col style={{ width: 36 }} /><col /><col /><col style={{ width: 64 }} /><col className="status" style={{ width: 132 }} /></colgroup>
              <thead><tr><th><input type="checkbox" aria-label="Select every visible table" checked={visible.some(importable) && visible.filter(importable).every(r => selected.includes(r.key))} disabled={!visible.some(importable)} onChange={() => { const keys = visible.filter(importable).map(r => r.key); setSelected(sel => keys.every(k => sel.includes(k)) ? sel.filter(k => !keys.includes(k)) : [...new Set([...sel, ...keys])]); }} /></th><th>Table</th><th>Ontology class</th><th style={{ textAlign: "right" }}>Cols</th><th><span className="txt">Status</span></th></tr></thead>
              <tbody>
                {groups.map(({ sc, rows, all: everything, st }) => { const openable = everything.filter(t => !t.imported); return (
                  <FragmentGroup key={sc.id}>
                    <tr className="group"><td colSpan={5}>
                      <button type="button" className="all" aria-label={`Select all in ${short(sc.label)}`} disabled={!editable || openable.length === 0} title={openable.length ? `Tick the ${plural(openable.length, "table")} not yet in the snapshot` : "Every table is in the snapshot"} onClick={() => toggleSchema(sc.id)}>Select all</button>
                      <span className="name">{short(sc.label)}</span><span className="sum">{st?.loading ? "reading…" : st?.error ? "could not read" : `${plural(everything.length, "table")} · ${everything.filter(t => t.imported).length} in snapshot`}</span>
                    </td></tr>
                    {st?.error && <tr><td colSpan={5}><ErrorNotice error={st.error} action={<span className="small">{permissionHint(st.error)}</span>} /></td></tr>}
                    {st?.loading && <tr><td colSpan={5}><Skeleton h={18} /></td></tr>}
                    {st?.data && everything.length === 0 && <tr><td colSpan={5} className="muted small">No tables.</td></tr>}
                    {rows.map(r => { const on = current?.key === r.key; return (
                      <tr key={r.key} className={`data ${on ? "on" : ""}`} aria-selected={on}>
                        <td><input type="checkbox" aria-label={`Select ${r.t.name}`} checked={selected.includes(r.key)} disabled={!importable(r)} title={r.t.imported ? "Already in the snapshot" : !editable ? "Only the lease holder of a draft can import" : "Tick for import"} onClick={e => { if (e.shiftKey) { e.preventDefault(); toggle(r, true); } }} onChange={e => { if (!(e.nativeEvent as MouseEvent).shiftKey) toggle(r); }} /></td>
                        <td className="cell"><a href="#" className="tname" title={r.t.name} onClick={e => { e.preventDefault(); pick(r); }}>{r.t.name}</a><span className="sub">{r.short}</span></td>
                        <td className="cell" title={r.t.cls ?? undefined}>{r.t.cls ? <a href="#" onClick={e => { e.preventDefault(); go("ontology", { cls: r.t.cls!, view: "map" }); }}>{r.t.cls}</a> : <span className="unmapped">unmapped</span>}</td>
                        <td className="num">{r.t.cols}</td>
                        <td><span className={`status-pill ${r.t.imported ? "in" : ""}`} title={r.t.imported ? "In snapshot" : "Not imported"}><Dot color={r.t.imported ? BLUE : GREY} /><span className="txt">{r.t.imported ? "In snapshot" : "Not imported"}</span></span></td>
                      </tr>); })}
                  </FragmentGroup>); })}
                {!anyLoading && visible.length === 0 && all.length > 0 && <tr><td colSpan={5} className="detail-empty">No table matches. Clear the search or the filters.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>

        <aside className="meta-detail" aria-label="Table details">
          {!current && (anyLoading ? <Skeleton h={120} /> : <div className="detail-empty">Pick a table to see its columns.</div>)}
          {current && (
            <>
              <div className="hero">
                <div className="path">{full}</div>
                <div className="title"><h2>{current.t.name}</h2><span className="status-pill"><Dot color={current.t.imported ? "#fff" : GREY} />{current.t.imported ? "In snapshot" : "Not imported"}</span></div>
                <div className="facts">
                  <dl>
                    <div><dt>Class</dt><dd>{cls ? <a href="#" onClick={e => { e.preventDefault(); go("ontology", { cls, view: "map" }); }}>{cls}</a> : "—"}</dd></div>
                    <div><dt>Columns</dt><dd>{detail.data ? cols.length : current.t.cols}</dd></div>
                    <div><dt>Key</dt><dd>{keyCols.length ? keyCols.join(", ") : "—"}</dd></div>
                    {caps.quality && <div><dt>DQ score</dt><dd>{dqScore != null ? `${dqScore}%` : "—"}</dd></div>}
                  </dl>
                  {current.t.imported
                    ? <Button onClick={removeCurrent} disabled={!editable || !!busy} title={editable ? "Take the table out of this draft's snapshot" : "Only the lease holder of a draft can change the snapshot"}>{busy === "one" && <Spinner blue />}Remove from snapshot</Button>
                    : <Button onClick={addCurrent} disabled={!editable || !!busy} title={editable ? "Capture columns, keys and comments into this draft" : "Only the lease holder of a draft can change the snapshot"}>{busy === "one" && <Spinner blue />}Add to snapshot</Button>}
                </div>
              </div>
              {(caps.profiling || caps.glossary || caps.quality) && (
                <div className="act-tiles">
                  {caps.profiling && <button type="button" className="act-tile" aria-pressed={tab === "profile"} onClick={() => { setProfiled(true); setTab("profile"); }}><span className="ic"><Icon name="analytics" size={12} /></span><span><b>Profile</b><span>Rows, nulls, ranges</span></span></button>}
                  {caps.glossary && <button type="button" className="act-tile" aria-pressed={tab === "glossary"} onClick={() => setTab("glossary")}><span className="ic"><Icon name="rules" size={12} /></span><span><b>Glossary</b><span>Terms and KPIs</span></span></button>}
                  {caps.quality && <button type="button" className="act-tile" aria-pressed={tab === "dq"} onClick={() => setTab("dq")}><span className="ic"><Icon name="quality" size={12} /></span><span><b>Table DQ</b><span>Rules and scores</span></span></button>}
                </div>
              )}
              <Tabs<Tab> value={tabs.some(t => t.id === tab) ? (tab as Tab) : "columns"} onChange={t => { if (t === "profile") setProfiled(true); setTab(t); }} items={tabs} />

              {(tab === "columns" || !tabs.some(t => t.id === tab)) && (
                <>
                  {detail.loading && <div style={{ padding: "12px 0", display: "grid", gap: 10 }}><Skeleton h={16} /><Skeleton h={16} /><Skeleton h={16} /></div>}
                  {detail.error && <ErrorNotice error={detail.error} action={<span className="small">{permissionHint(detail.error)}</span>} />}
                  {detail.data && cols.length === 0 && <p className="muted" style={{ padding: "12px 0" }}>The catalog reports no columns for this table.</p>}
                  {cols.length > 0 && (
                    <table className="cols">
                      <colgroup><col style={{ width: "40%" }} /><col style={{ width: 88 }} /><col /><col style={{ width: 44 }} />{caps.quality && <col style={{ width: 64 }} />}</colgroup>
                      <thead><tr><th>Column</th><th>Type</th><th>Description</th><th>Key</th>{caps.quality && <th style={{ textAlign: "right" }}>DQ</th>}</tr></thead>
                      <tbody>
                        {cols.map(c => { const issue = dqIssues.find(d => d.column === c.name); const term = termByCol[c.name]; return (
                          <tr key={c.name}>
                            <td className="name" title={c.name}>{c.name}{term && <> <a href="#" className="pill mini" title="Glossary term" style={{ fontFamily: "var(--font)" }} onClick={e => { e.preventDefault(); setTab("glossary"); setGq(term); }}>{term}</a></>}</td>
                            <td className="type">{c.type}</td>
                            <td className="desc">{c.comment || <span className="muted-3">—</span>}</td>
                            <td className={`key ${c.keyInferred ? "inferred" : ""}`} title={c.key ? (c.keyInferred ? "Inferred from the name" : "Declared in the catalog") : undefined}>{c.key === "pk" ? "PK" : c.key === "fk" ? "FK" : ""}</td>
                            {caps.quality && <td className="num" style={{ textAlign: "right", fontWeight: 700, color: issue ? "var(--orange-text)" : "var(--blue-dark)" }}>{issue ? `${issue.count} bad` : "100%"}</td>}
                          </tr>); })}
                      </tbody>
                    </table>
                  )}
                </>
              )}

              {tab === "profile" && caps.profiling && (
                <div style={{ padding: "12px 0" }}>
                  {profile.loading && <Skeleton h={60} />}
                  {prof && <>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(4,minmax(0,1fr))", gap: 8, marginBottom: 12 }}>
                      {[["Rows", prof.rows, "count(*)"], ["Nulls", String(Object.values(prof.cols).filter(c => c[0] > 0).length), "columns with nulls"], ["Duplicates", prof.dup, "on inferred key"], ["Freshness", prof.fresh, "last ETL write"]].map(([k, v, sub]) => <div key={k} style={{ padding: "10px 12px", border: "1px solid var(--line)", borderRadius: 8 }}><div className="label-caps" style={{ fontSize: 10.5 }}>{k}</div><div style={{ fontSize: 18, fontWeight: 800, letterSpacing: "-.02em" }}>{v}</div><div className="muted-3" style={{ fontSize: 11 }}>{sub}</div></div>)}
                    </div>
                    <table className="cols"><thead><tr><th>Column</th><th>Nulls</th><th>Distinct</th></tr></thead><tbody>
                      {cols.map(c => { const p = prof.cols[c.name] ?? [0, 0]; const color = p[0] > 30 ? "#B84F00" : p[0] > 0 ? "#5F5F60" : BLUE; return <tr key={c.name}><td className="name">{c.name}</td><td><span className="row"><span style={{ width: 44, height: 6, borderRadius: 3, background: "var(--surface-3)", overflow: "hidden" }}><i style={{ display: "block", height: "100%", width: `${Math.max(2, p[0])}%`, background: color }} /></span><span className="mono" style={{ fontSize: 11.5, color }}>{p[0]}%</span></span></td><td className="mono" style={{ fontSize: 11.5 }}>{p[1].toLocaleString()}</td></tr>; })}
                    </tbody></table>
                    {dbx && <div style={{ marginTop: 10 }}><Button size="sm" variant="outline" onClick={() => say(`Inferred keys for ${table}`)}>Infer keys</Button></div>}
                  </>}
                </div>
              )}

              {tab === "glossary" && caps.glossary && (
                <div style={{ padding: "12px 0" }}>
                  <div className="row" style={{ marginBottom: 12 }}>
                    <div className="search-wrap"><Icon name="search" stroke="#7A7A80" /><input aria-label="Search glossary" className="input sm" placeholder="Terms, classes, columns…" value={gq} onChange={e => setGq(e.target.value)} /></div>
                    <Button size="sm" active={gScope} onClick={() => setGScope(s => !s)} style={{ whiteSpace: "nowrap" }}>This table only</Button>
                    <Button size="sm" variant="primary" onClick={() => say("New glossary term")}>New term</Button>
                  </div>
                  {glossaryRows.map(g => (
                    <div key={g.term} style={{ padding: "10px 0", borderTop: "1px solid var(--line-2)" }}>
                      <div className="row between" style={{ alignItems: "baseline", gap: 10 }}><strong style={{ fontSize: 13, fontWeight: 700 }}>{g.term}</strong><span className="muted-2" style={{ fontSize: 11 }}>{g.steward}</span></div>
                      <div style={{ fontSize: 12.5, color: "var(--ink-2)", margin: "4px 0 8px" }}>{g.def}</div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, fontSize: 11 }}><a href="#" className="pill blue" onClick={e => { e.preventDefault(); go("ontology", { cls: g.cls, view: "map" }); }}>{g.cls}</a>{g.cols.map(c => <span key={c} className="pill outline mono" style={{ color: "var(--muted)", fontWeight: 400 }}>{c}</span>)}</div>
                    </div>
                  ))}
                  {glossaryRows.length === 0 && <p className="muted" style={{ fontSize: 12.5 }}>No term matches “{gq}”. <a href="#" style={{ fontWeight: 600 }} onClick={e => { e.preventDefault(); say(`Creating term “${gq}”`); }}>Create it</a>.</p>}
                </div>
              )}

              {tab === "dq" && caps.quality && (
                <div style={{ padding: "12px 0" }}>
                  <div className="row between" style={{ marginBottom: 12 }}><div className="muted" style={{ fontSize: 12.5 }}>Constraints that touch <span className="mono">{table}</span>.</div><div className="row"><Button size="sm" onClick={() => go("quality")}>Open Data quality</Button><Button size="sm" variant="primary" onClick={() => { setDqRan(true); if (!profiled) setProfiled(true); say(`Quick checks on ${table} · ${dqRows.length + (dqRan ? 0 : 2)} constraints run`); }}>Run quick checks</Button></div></div>
                  <table className="cols"><thead><tr><th>Constraint</th><th>Column</th><th>Severity</th><th style={{ textAlign: "right" }}>Violations</th></tr></thead><tbody>
                    {dqRows.map((r, i) => <tr key={i}><td style={{ fontWeight: 600 }}>{r.name}</td><td className="type">{r.column} · {r.kind}</td><td><span className="row"><Dot color={r.dot} />{r.severity}</span></td><td className="num" style={{ textAlign: "right", fontWeight: 700, color: r.bad ? "#B84F00" : "var(--ink)" }}>{r.count}</td></tr>)}
                    {dqRows.length === 0 && <tr><td colSpan={4} className="muted">No constraint touches this table yet.</td></tr>}
                  </tbody></table>
                  <div style={{ marginTop: 12, display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}><span className="muted small">Add a quick check:</span>{["unique", "min_count", "pattern", "in", "no_orphans"].map(k => <Button key={k} dashed className="mono" style={{ fontSize: 11.5 }} onClick={() => say(`Added ${k} check on ${table}`)}>{k}</Button>)}</div>
                </div>
              )}
            </>
          )}
        </aside>
      </div>
    </div>
  );
}

/** A keyed wrapper for a schema's rows inside one tbody (React fragments cannot carry the group's key alone). */
function FragmentGroup({ children }: { children: React.ReactNode }) { return <>{children}</>; }
