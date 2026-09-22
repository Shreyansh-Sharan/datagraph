import { useEffect, useState } from "react";
import { Button, Card, Dialog, Dot, ErrorNotice, Glyph, Label, Pill, Skeleton, Spinner, Tabs } from "@/components/ui";
import { Icon } from "@/components/icons";
import { Stage, glyphOf, type StageEdge, type StageNode } from "@/components/Stage";

import { useApp, useLoad } from "@/state/app";
import { useDomain, useParam } from "@/state/domain";
import { STATE_COLOR, type DriftIssue, type SnapshotTable } from "@/api";

type Panel = "status" | "data" | "sql";
const BLUE = "#2249FF", ORANGE = "#FF7000", DARK = "#1636E0";

export function Mapping() {
  const { api, config, say } = useApp();
  const { domain, version, editable, sourceKind } = useDomain();
  const [clsId, setCls] = useParam("cls", "");
  const [panel, setPanel] = useParam("panel", "status");
  const dbx = sourceKind === "databricks";
  const v = version?.version ?? 0;
  const classes = useLoad(() => api.ontology(domain.name, v), [domain.name, v]);
  const mapping = useLoad(() => api.mapping(domain.name, v), [domain.name, v]);
  const kpis = useLoad(() => api.mappingKpis(domain.name, v), [domain.name, v]);
  const snapshot = useLoad(() => api.snapshot(domain.name, v).catch(() => [] as SnapshotTable[]), [domain.name, v]);
  const preview = useLoad(() => panel === "data" && clsId ? api.tablePreview(domain.name, clsId, v) : Promise.resolve(null), [domain.name, clsId, panel, v, mapping.data]);
  const sql = useLoad(() => panel === "sql" && clsId ? api.classSql(domain.name, clsId, v) : Promise.resolve(""), [domain.name, clsId, panel, config.sourceKind, v, mapping.data]);
  const [mapDialog, setMapDialog] = useState(false);
  const [unmapDialog, setUnmapDialog] = useState(false);
  const [relEdit, setRelEdit] = useState<string | null>(null);
  const [drift, setDrift] = useState<DriftIssue[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [aiStatus, setAiStatus] = useState<{ progress: string; since: number } | null>(null);
  const [skipped, setSkipped] = useState<string[]>([]);
  const [tick, setTick] = useState(0);
  useEffect(() => { if (!aiStatus) return; const t = setInterval(() => setTick(x => x + 1), 1000); return () => clearInterval(t); }, [aiStatus]);
  // A suggestion started earlier (or from another tab) is still running on the server: show it and reload when it ends.
  useEffect(() => {
    let alive = true;
    api.runningAiJob(domain.name, v, "suggest-mapping", p => { if (alive) setAiStatus({ progress: p.progress, since: p.startedAt ? new Date(p.startedAt).getTime() : Date.now() }); })
      .then(end => { if (!alive || !end) return; setAiStatus(null); mapping.reload(); kpis.reload(); say(end.status === "succeeded" ? "AI suggestion finished: mapping updated" : `AI suggestion failed: ${end.progress}`); })
      .catch(() => { /* status is a courtesy */ });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [domain.name, v]);

  const list = classes.data ?? []; const M = mapping.data ?? {};
  const sel = list.find(c => c.id === clsId) ?? list[0];
  const m = sel ? M[sel.id] : undefined;
  const state = (id: string) => M[id]?.state ?? "unmapped";
  const edges: StageEdge[] = list.flatMap(c => c.rels.map(r => ({ from: c.id, to: r.target, label: r.name, color: "#B9C4FF" })));
  const nodes: StageNode[] = list.map(c => ({ id: c.id, label: c.id, glyph: glyphOf(c.id), x: c.x, y: c.y, fill: STATE_COLOR[state(c.id)], border: c.id === sel?.id ? BLUE : undefined, selected: c.id === sel?.id, title: state(c.id), group: state(c.id), props: c.attrs.length + c.rels.length }));
  const groups = [{ id: "complete", label: "complete", color: STATE_COLOR.complete }, { id: "partial", label: "partial", color: STATE_COLOR.partial }, { id: "unmapped", label: "unmapped", color: STATE_COLOR.unmapped }];
  const tableText = m ? (m.fullName ?? (m.table ? m.table.join(".") : "SQL query")) : "";
  const k = kpis.data;
  const excluded = new Set(m?.excluded ?? []);
  const snapOf = (full?: string) => (snapshot.data ?? []).find(t => full && t.table.toLowerCase() === full.toLowerCase());
  const columns = snapOf(m?.fullName)?.columnNames ?? preview.data?.columns ?? [];
  const bound = m ? Object.fromEntries(Object.entries(m.cols).map(([a, c]) => [c, a])) : {};

  /** Runs one edit, reloads what it changed and tells the user; errors become toasts. */
  const edit = async (label: string, fn: () => Promise<unknown>, msg: string | ((r: unknown) => string)) => {
    if (busy) return; setBusy(label);
    try { const r = await fn(); mapping.reload(); kpis.reload(); say(typeof msg === "function" ? msg(r) : msg); return true; }
    catch (e) { say(e instanceof Error ? e.message : String(e)); return false; }
    finally { setBusy(null); }
  };
  const bind = (attr: string, col: string | null) => sel && edit("bind", () => api.bindAttribute(domain.name, v, sel.id, attr, col), col ? `${attr} → ${col}` : `${attr} unbound`);
  const exclude = (prop: string, on: boolean) => sel && edit("exclude", () => api.excludeProperty(domain.name, v, sel.id, prop, on), on ? `${prop} excluded from the mapping` : `${prop} back in the mapping`);
  const showDrift = async () => { if (busy) return; setBusy("drift"); try { const d = await api.drift(domain.name, v); setDrift(d); say(d.length ? `${d.length} drift issue${d.length === 1 ? "" : "s"}` : "No drift: the source still matches the mapping"); } catch (e) { say(e instanceof Error ? e.message : String(e)); } finally { setBusy(null); } };
  const exportR2rml = async () => { try { const ttl = await api.r2rml(domain.name, v); const blob = new Blob([ttl], { type: "text/turtle" }); const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = `${domain.name}-v${v}.r2rml.ttl`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); say("R2RML exported"); } catch (e) { say(e instanceof Error ? e.message : String(e)); } };
  const suggest = async () => {
    setAiStatus({ progress: "Starting", since: Date.now() });
    setSkipped([]);
    try { await edit("suggest", () => api.suggestMapping(domain.name, v, p => setAiStatus({ progress: p.progress, since: p.startedAt ? new Date(p.startedAt).getTime() : Date.now() })), r => { const x = r as { classes: number; relations: number; skipped: string[] }; setSkipped(x.skipped ?? []); return `AI suggested bindings for ${x.classes} class${x.classes === 1 ? "" : "es"} and ${x.relations} relationship${x.relations === 1 ? "" : "s"}${x.skipped?.length ? ` · ${x.skipped.length} skipped` : ""}`; }); }
    finally { setAiStatus(null); }
  };
  const suggestRelations = async () => {
    setAiStatus({ progress: "Starting", since: Date.now() }); setSkipped([]);
    try { await edit("relations", () => api.suggestRelations(domain.name, v, p => setAiStatus({ progress: p.progress, since: p.startedAt ? new Date(p.startedAt).getTime() : Date.now() })), r => { const x = r as { added: number; declared: number; byName: number; ai: number; skipped: string[]; unmappable: string[] }; setSkipped([...x.skipped, ...x.unmappable.map(u => `not mappable yet: ${u}`)]); return `${x.added} relationship${x.added === 1 ? "" : "s"} mapped · ${x.declared} from declared keys, ${x.byName} by matching names, ${x.ai} by the AI`; }); }
    finally { setAiStatus(null); }
  };
  const elapsed = aiStatus ? Math.max(0, Math.round((Date.now() - aiStatus.since) / 1000)) : 0;
  void tick;

  return (
    <>
      <div className="page-head">
        <div><h1>Mapping</h1><p>Bind each class to a table and its attributes to columns; relationships follow foreign keys or link tables.</p></div>
        <div className="actions">
          <Button onClick={showDrift} disabled={!!busy} title="Re-reads every mapped table from the source; can take a while on a large mapping">{busy === "drift" && <Spinner blue />}Drift</Button>
          <Button onClick={exportR2rml}>R2RML</Button>
          {editable && <Button disabled={!!busy} onClick={() => edit("exclude-unmapped", () => api.excludeUnmapped(domain.name, v), "Unmapped attributes and relationships excluded")}>Exclude unmapped</Button>}
          {editable && <Button disabled={!!busy} title="Map the relationships still open: declared foreign keys, then columns named like the target's key, then the AI for the rest, one pair of tables at a time" onClick={suggestRelations}>{busy === "relations" && <Spinner blue />}Fill relationships</Button>}
          {editable && <Button variant="primary" disabled={!!busy} onClick={suggest}>{busy === "suggest" && <Spinner />}Suggest with AI</Button>}
        </div>
      </div>
      {aiStatus && (
        <div className="notice" role="status" aria-live="polite" style={{ marginBottom: 16 }}>
          <div className="row" style={{ gap: 8, fontWeight: 600 }}><Spinner blue />{busy === "relations" ? "Filling relationships" : "Suggesting with AI"} · {aiStatus.progress} · {elapsed >= 60 ? `${Math.floor(elapsed / 60)} min ${elapsed % 60} s` : `${elapsed} s`}</div>
          <div className="muted xs" style={{ marginTop: 4 }}>The source is read table by table, then the whole ontology goes to the AI provider in one request; with dozens of tables that step alone takes minutes. The job runs on the server, so you can leave this screen and come back.</div>
        </div>
      )}
      {skipped.length > 0 && (
        <Card style={{ marginBottom: 16, borderColor: "var(--orange)" }}>
          <div className="row between"><h2 className="h2">{skipped.length} suggestion{skipped.length === 1 ? "" : "s"} skipped</h2><Button size="xs" variant="ghost" onClick={() => setSkipped([])}>Close</Button></div>
          <p className="muted small" style={{ margin: "4px 0 8px" }}>The AI named columns, properties or classes that do not exist there. Everything else was applied; fix these by hand on the class, with the relationship form.</p>
          <div style={{ maxHeight: 220, overflowY: "auto" }}>{skipped.map((x, i) => <div key={i} className="mono" style={{ padding: "4px 0", borderTop: "1px solid var(--line-2)", fontSize: 11.5, color: "var(--ink-2)" }}>{x}</div>)}</div>
        </Card>
      )}
      {drift && (
        <Card style={{ marginBottom: 16, borderColor: drift.length ? "var(--orange)" : "var(--blue-border)" }}>
          <div className="row between"><h2 className="h2">Schema drift</h2><Button size="xs" variant="ghost" onClick={() => setDrift(null)}>Close</Button></div>
          {drift.length === 0 && <p className="muted small" style={{ marginTop: 6 }}>Every table and column the mapping reads is still in the snapshot.</p>}
          {drift.map((d, i) => <div key={i} className="row" style={{ gap: 10, padding: "6px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}><Dot color={d.severity === "error" ? ORANGE : "#B3B3B7"} /><span className="mono">{d.table}{d.column ? `.${d.column}` : ""}</span><span style={{ color: "var(--ink-2)" }}>{d.detail}</span><span className="muted-2 xs" style={{ marginLeft: "auto" }}>{d.mapping_ref}</span></div>)}
        </Card>
      )}
      <div className="grid cols-5" style={{ marginBottom: 16 }}>
        {k && [["Completion", `${k.completion}%`, BLUE], ["Classes mapped", `${k.classesMapped[0]} / ${k.classesMapped[1]}`, "var(--ink)"], ["Attributes", `${k.attributes[0]} / ${k.attributes[1]}`, "var(--ink)"], ["Relationships", `${k.relationships[0]} / ${k.relationships[1]}`, "var(--ink)"], ["Excluded", String(k.excluded), "var(--muted)"]].map(([label, value, color]) => <Card key={label} className="kpi"><div className="label-caps" style={{ fontSize: 10.5 }}>{label}</div><div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.02em", color }}>{value}</div></Card>)}
      </div>
      <div className="bar" style={{ marginBottom: 20 }}><i style={{ width: `${k?.completion ?? 0}%` }} /></div>
      {classes.error && <ErrorNotice error={classes.error} action={<span className="small">Draft the ontology first: the mapping binds its classes to tables.</span>} />}
      {classes.loading ? <Skeleton h={400} /> : list.length > 0 && (
        <Stage nodes={nodes} edges={edges} height={520} dotted groups={groups} spotlight={!!clsId} onSelect={id => setCls(id)} onExpand={id => { setCls(id); setPanel("status"); }} />
      )}
      {sel && (
        <Card flush style={{ marginTop: 16 }}>
          <div className="row" style={{ gap: 12, padding: "12px 20px", borderBottom: "1px solid var(--line)" }}>
            <Glyph size={26} color={STATE_COLOR[state(sel.id)]}>{glyphOf(sel.id)}</Glyph>
            <strong style={{ fontSize: 15, fontWeight: 800 }}>{sel.id}</strong>
            <Pill dot={STATE_COLOR[state(sel.id)]}>{state(sel.id)}</Pill>
            <span className="mono muted small">{tableText}</span>
            <span className="spacer" />
            {m ? <>
              <Button size="sm" onClick={() => setPanel("data")}>Preview rows</Button>
              {editable && <Button size="sm" onClick={() => setMapDialog(true)}>Change table</Button>}
              {editable && <Button size="sm" variant="danger" onClick={() => setUnmapDialog(true)}>Unmap</Button>}
            </> : editable && <Button size="sm" variant="primary" onClick={() => setMapDialog(true)}>Map to a table</Button>}
          </div>
          <Tabs<Panel> pad value={(panel as Panel) || "status"} onChange={p => setPanel(p)} items={[{ id: "status", label: "Status" }, { id: "data", label: "Data" }, { id: "sql", label: "SQL" }]} />
          {!m && <div className="muted" style={{ padding: "32px 20px", textAlign: "center" }}>This class has no table yet. {editable ? "Map it to a table from the snapshot to bind its attributes." : "Take the lease on a draft to map it."}</div>}
          {m && panel === "status" && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 24px", padding: "8px 20px 16px" }}>
              <div>
                <h3 className="label-caps" style={{ margin: "12px 0 6px", fontSize: 12 }}>Attributes</h3>
                {sel.attrs.map(a => { const c = m.cols[a.name]; const ex = excluded.has(a.name); return (
                  <div key={a.name} style={{ display: "grid", gridTemplateColumns: "1fr 1.2fr auto", alignItems: "center", gap: 12, padding: "8px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}>
                    <span style={{ color: ex ? "var(--muted-2)" : undefined }}>{a.name}{ex && <span className="muted-2 xs"> · excluded</span>}</span>
                    {editable && !ex
                      ? <select aria-label={`Column for ${a.name}`} className="select mono sm" value={c ?? ""} disabled={!!busy} onChange={e => bind(a.name, e.target.value || null)}>
                          <option value="">{columns.length ? "unmapped" : "unmapped · no columns known"}</option>
                          {columns.map(col => <option key={col} value={col}>{col}{bound[col] && bound[col] !== a.name ? ` (${bound[col]})` : ""}</option>)}
                          {c && !columns.includes(c) && <option value={c}>{c}</option>}
                        </select>
                      : <span className="mono row" style={{ fontSize: 12, color: c ? "var(--ink)" : ex ? "var(--muted-2)" : "#B84F00", gap: 6 }}><Dot color={c ? BLUE : ex ? "#CFCFD2" : ORANGE} />{c ?? (ex ? "—" : "unmapped")}</span>}
                    {editable && <Button size="xs" variant="ghost" disabled={!!busy} onClick={() => exclude(a.name, !ex)}>{ex ? "Include" : "Exclude"}</Button>}
                  </div>); })}
                {sel.attrs.length === 0 && <p className="muted-2" style={{ fontSize: 12.5, margin: "8px 0" }}>No attributes on this class.</p>}
              </div>
              <div>
                <h3 className="label-caps" style={{ margin: "12px 0 6px", fontSize: 12 }}>Relationships</h3>
                {sel.rels.map(r => { const val = m.rels?.[r.name]; const ex = excluded.has(r.name); return (
                  <div key={r.name} style={{ padding: "8px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1.4fr auto", alignItems: "center", gap: 12 }}>
                      <span style={{ color: ex ? "var(--muted-2)" : undefined }}>{r.name} <span className="muted">→ {r.target}</span>{ex && <span className="muted-2 xs"> · excluded</span>}</span>
                      <span className="mono row" style={{ fontSize: 11.5, color: val ? "var(--ink)" : ex ? "var(--muted-2)" : "#B84F00", gap: 6 }}><Dot color={val ? BLUE : ex ? "#CFCFD2" : ORANGE} />{val ?? (ex ? "—" : "unmapped")}</span>
                      {editable && <span className="row" style={{ gap: 4 }}>{!ex && <Button size="xs" disabled={!!busy} onClick={() => setRelEdit(relEdit === r.name ? null : r.name)}>{val ? "Change" : "Map"}</Button>}<Button size="xs" variant="ghost" disabled={!!busy} onClick={() => exclude(r.name, !ex)}>{ex ? "Include" : "Exclude"}</Button></span>}
                    </div>
                    {relEdit === r.name && (
                      M[r.target]?.fullName
                        ? <RelationForm rel={r.name} target={r.target} sourceKey={m.key} sourceColumns={columns} targetKey={M[r.target]?.key ?? ""} onCancel={() => setRelEdit(null)}
                            onSave={async fk => { const ok = await edit("relation", () => api.mapRelation(domain.name, v, sel.id, r.name, [m.key], [fk]), `${r.name}: ${sel.id}.${fk} → ${r.target}`); if (ok) setRelEdit(null); }} />
                        : <p className="muted-2 xs" style={{ margin: "6px 0 0" }}>Map {r.target} to a table first; the relationship joins the two tables.</p>
                    )}
                  </div>); })}
                {sel.rels.length === 0 && <p className="muted-2" style={{ fontSize: 12.5, margin: "8px 0" }}>No relationships from this class.</p>}
              </div>
            </div>
          )}
          {m && panel === "data" && (
            <>
              <div className="muted small" style={{ padding: "12px 20px 4px" }}>First 5 rows of <span className="mono">{tableText}</span>. {editable ? "Click a column header to bind it to the next unbound attribute." : "Bindings are shown as badges."}</div>
              {preview.error && <div style={{ padding: "0 20px 16px" }}><ErrorNotice error={preview.error} /></div>}
              {preview.loading && <div style={{ padding: "8px 20px 16px" }}><Skeleton h={120} /></div>}
              {preview.data && preview.data.columns.length > 0 && (
                <div style={{ overflowX: "auto", padding: "0 20px 16px" }}>
                  <div style={{ display: "grid", gridTemplateColumns: `repeat(${preview.data.columns.length},minmax(120px,1fr))`, minWidth: 600, border: "1px solid var(--line)", borderRadius: 8, overflow: "hidden" }}>
                    {preview.data.columns.map(c => { const isKey = c === m.key; const b = bound[c]; return (
                      <button key={c} type="button" title={editable ? "Bind this column to the next unbound attribute" : undefined} disabled={!editable || !!busy} onClick={() => { const attr = sel.attrs.find(a => !m.cols[a.name] && !excluded.has(a.name)); if (attr) bind(attr.name, c); else say("All attributes are bound"); }}
                        style={{ textAlign: "left", padding: "8px 10px", background: "var(--surface-3)", border: 0, borderBottom: "1px solid var(--line)", font: "500 11.5px var(--mono)", color: "var(--ink)", cursor: editable ? "pointer" : "default", display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                        {c}{(isKey || b) && <span className="pill mini" style={{ background: isKey ? BLUE : "var(--blue-soft)", color: isKey ? "#fff" : DARK, fontFamily: "var(--font)" }}>{isKey ? "ID" : b}</span>}
                      </button>); })}
                    {preview.data.rows.flatMap((r, i) => r.map((val, j) => <span key={`${i}-${j}`} style={{ padding: "7px 10px", borderTop: "1px solid var(--line-2)", fontSize: 12, color: val == null ? "#B3B3B7" : "var(--ink)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{val ?? "null"}</span>))}
                  </div>
                </div>
              )}
              {preview.data && preview.data.columns.length === 0 && <p className="muted" style={{ padding: "0 20px 16px" }}>Data preview is available for table-backed classes.</p>}
            </>
          )}
          {m && panel === "sql" && (
            <div style={{ padding: "16px 20px" }}>
              <div className="row between" style={{ marginBottom: 8 }}><span className="muted small">Compiled for the running adapter · <strong style={{ color: DARK, fontWeight: 600 }}>{dbx ? "Databricks" : "Postgres"}</strong> dialect</span><Button size="xs" style={{ height: 26 }} onClick={() => { navigator.clipboard?.writeText(sql.data ?? "").catch(() => {}); say("SQL copied"); }}><Icon name="copy" size={12} />Copy</Button></div>
              {sql.error && <ErrorNotice error={sql.error} />}
              {sql.loading ? <Skeleton h={160} /> : <pre className="pre">{sql.data}</pre>}
            </div>
          )}
        </Card>
      )}
      {sel && <MapTableDialog open={mapDialog} cls={sel.id} current={m?.fullName} tables={snapshot.data ?? []} onClose={() => setMapDialog(false)}
        onMap={async (table, key) => { const ok = await edit("map", () => api.mapClass(domain.name, v, sel.id, table, [key]), `${sel.id} mapped to ${table}`); if (ok) setMapDialog(false); }} />}
      {sel && <Dialog title={`Unmap ${sel.id}?`} open={unmapDialog} onClose={() => setUnmapDialog(false)} footer={<><Button onClick={() => setUnmapDialog(false)}>Cancel</Button><Button variant="danger" onClick={async () => { const ok = await edit("unmap", () => api.unmapClass(domain.name, v, sel.id), `${sel.id} unmapped`); if (ok) setUnmapDialog(false); }}>Unmap class</Button></>}>
        <p className="muted">The table, its attribute bindings and every relationship from or to {sel.id} are removed from the mapping. The ontology is not changed.</p>
      </Dialog>}
      {sel && !editable && <p className="muted-2 xs" style={{ marginTop: 10 }}>Only the lease holder of a draft can change the mapping.</p>}
    </>
  );
}

/** Choose a snapshot table (imported on the Metadata screen) and its key column for a class. */
function MapTableDialog({ open, cls, current, tables, onClose, onMap }: { open: boolean; cls: string; current?: string; tables: SnapshotTable[]; onClose: () => void; onMap: (table: string, key: string) => Promise<void> }) {
  const [table, setTable] = useState(current ?? "");
  const [key, setKey] = useState("");
  const t = tables.find(x => x.table === (table || current));
  const keyValue = key || t?.primaryKey[0] || t?.columnNames[0] || "";
  return (
    <Dialog title={`Map ${cls} to a table`} open={open} onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!(table || current) || !keyValue} onClick={() => onMap(table || current || "", keyValue)}>Map class</Button></>}>
      {tables.length === 0 && <p className="muted" style={{ marginBottom: 12 }}>The snapshot is empty. Import the tables you need on the Metadata screen first.</p>}
      <Label>Table</Label>
      <select id="map-table" aria-label="Table" className="select mono full" value={table || current || ""} onChange={e => { setTable(e.target.value); setKey(""); }} style={{ marginBottom: 12 }}>
        <option value="">Choose a snapshot table…</option>
        {tables.map(x => <option key={x.table} value={x.table}>{x.table} · {x.columns} cols</option>)}
      </select>
      <Label>Key column</Label>
      <select id="map-key" aria-label="Key column" className="select mono full" value={keyValue} onChange={e => setKey(e.target.value)} disabled={!t}>
        {(t?.columnNames ?? []).map(c => <option key={c} value={c}>{c}{t?.primaryKey.includes(c) ? " · primary key" : ""}</option>)}
      </select>
      <div className="muted-2 xs" style={{ marginTop: 6 }}>Entity IRIs are minted from the key: one entity per distinct key value.</div>
    </Dialog>
  );
}

/** A relationship reads a foreign key on the source class's table: pick the column that holds the target's key. */
function RelationForm({ rel, target, sourceKey, sourceColumns, targetKey, onCancel, onSave }: { rel: string; target: string; sourceKey: string; sourceColumns: string[]; targetKey: string; onCancel: () => void; onSave: (fkColumn: string) => Promise<void> }) {
  const guess = sourceColumns.find(c => c.toLowerCase() === targetKey.toLowerCase()) ?? sourceColumns.find(c => c.toLowerCase().includes(target.toLowerCase())) ?? sourceColumns[0] ?? "";
  const [fk, setFk] = useState(guess);
  return (
    <div className="row" style={{ gap: 6, marginTop: 6, flexWrap: "wrap", fontSize: 12 }}>
      <span className="muted xs">{rel}: row <span className="mono">{sourceKey}</span> → {target} whose <span className="mono">{targetKey || "key"}</span> is in column</span>
      <select aria-label={`Column holding the ${target} key for ${rel}`} className="select mono sm" value={fk} onChange={e => setFk(e.target.value)}>{sourceColumns.map(c => <option key={c} value={c}>{c}</option>)}</select>
      <Button size="xs" variant="primary" disabled={!fk} onClick={() => onSave(fk)}>Save</Button><Button size="xs" variant="ghost" onClick={onCancel}>Cancel</Button>
    </div>
  );
}
