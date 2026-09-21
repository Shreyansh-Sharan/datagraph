import { useState } from "react";
import { Button, Card, Dot, ErrorNotice, Glyph, Pill, Skeleton, Tabs } from "@/components/ui";
import { Icon } from "@/components/icons";
import { Stage, glyphOf, type StageEdge, type StageNode } from "@/components/Stage";
import { useApp, useLoad } from "@/state/app";
import { useDomain, useParam } from "@/state/domain";
import { STATE_COLOR, tableName } from "@/api";

type Panel = "status" | "data" | "sql";
const BLUE = "#2249FF", ORANGE = "#FF7000", DARK = "#1636E0";

export function Mapping() {
  const { api, config, say } = useApp();
  const { domain, version, editable } = useDomain();
  const [clsId, setCls] = useParam("cls", "Customer");
  const [panel, setPanel] = useParam("panel", "status");
  const [bindings, setBindings] = useState<Record<string, string>>({});
  const dbx = config.sourceKind === "databricks";
  const classes = useLoad(() => api.ontology(domain.name, version!.version), [domain.name, version?.version]);
  const mapping = useLoad(() => api.mapping(domain.name, version!.version), [domain.name, version?.version]);
  const kpis = useLoad(() => api.mappingKpis(domain.name, version!.version), [domain.name, version?.version]);
  const preview = useLoad(() => panel === "data" ? api.tablePreview(domain.name, clsId) : Promise.resolve(null), [domain.name, clsId, panel]);
  const sql = useLoad(() => panel === "sql" ? api.classSql(domain.name, clsId) : Promise.resolve(""), [domain.name, clsId, panel, config.sourceKind]);

  const list = classes.data ?? []; const M = mapping.data ?? {};
  const sel = list.find(c => c.id === clsId) ?? list[0];
  const m = sel ? M[sel.id] : undefined;
  const state = (id: string) => M[id]?.state ?? "unmapped";
  const edges: StageEdge[] = list.flatMap(c => c.rels.map(r => ({ from: c.id, to: r.target, label: r.name, color: "#B9C4FF" })));
  const nodes: StageNode[] = list.map(c => ({ id: c.id, label: c.id, glyph: glyphOf(c.id), x: c.x, y: c.y, fill: STATE_COLOR[state(c.id)], border: STATE_COLOR[state(c.id)], selected: c.id === sel?.id, title: state(c.id) }));
  const tableText = m ? (m.table ? tableName(config.sourceKind, domain.catalog, m.table[0], m.table[1]) : "SQL query") : "";
  const bound = m ? Object.fromEntries(Object.entries({ ...m.cols, ...Object.fromEntries(Object.entries(bindings).map(([col, attr]) => [attr, col])) }).map(([a, c]) => [c, a])) : {};
  const k = kpis.data;

  return (
    <>
      <div className="page-head">
        <div><h1>Mapping</h1><p>Bind each class to a table and its attributes to columns; relationships follow foreign keys or link tables.</p></div>
        <div className="actions"><Button onClick={() => say("Drift: fct_sales.channel_id has no target table")}>Drift</Button><Button onClick={() => say("R2RML exported")}>R2RML</Button><Button onClick={() => say("Unmapped attributes excluded")}>Exclude unmapped</Button><Button variant="primary" onClick={() => say("Suggesting bindings with AI…")}>Suggest with AI</Button></div>
      </div>
      <div className="grid cols-5" style={{ marginBottom: 16 }}>
        {k && [["Completion", `${k.completion}%`, BLUE], ["Classes mapped", `${k.classesMapped[0]} / ${k.classesMapped[1]}`, "var(--ink)"], ["Attributes", `${k.attributes[0]} / ${k.attributes[1]}`, "var(--ink)"], ["Relationships", `${k.relationships[0]} / ${k.relationships[1]}`, "var(--ink)"], ["Excluded", String(k.excluded), "var(--muted)"]].map(([label, value, color]) => <Card key={label} className="metric"><div className="label-caps">{label}</div><div className="v" style={{ color }}>{value}</div></Card>)}
      </div>
      <div className="bar" style={{ marginBottom: 20 }}><i style={{ width: `${k?.completion ?? 0}%` }} /></div>
      {classes.loading ? <Skeleton h={400} /> : (
        <Stage nodes={nodes} edges={edges} height={400} dotted onSelect={id => setCls(id)}
          legend={<><span><Dot color={BLUE} size={9} />complete</span><span><Dot color={ORANGE} size={9} />partial</span><span><Dot color="#B3B3B7" size={9} />unmapped</span></>} />
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
              <Button size="sm" onClick={() => setPanel("data")}>Preview triples</Button>
              {editable && <Button size="sm" onClick={() => say("Choose a table from the catalog")}>Change table</Button>}
              {editable && <Button size="sm" variant="danger" onClick={() => say(`Remove the mapping of ${sel.id}?`)}>Unmap</Button>}
            </> : editable && <Button size="sm" variant="primary" onClick={() => say("Choose a table from the catalog")}>Map to a table</Button>}
          </div>
          <Tabs<Panel> pad value={(panel as Panel) || "status"} onChange={p => setPanel(p)} items={[{ id: "status", label: "Status" }, { id: "data", label: "Data" }, { id: "sql", label: "SQL" }]} />
          {!m && <div className="muted" style={{ padding: "32px 20px", textAlign: "center" }}>This class has no table yet. Map it to a table to see its columns here.</div>}
          {m && panel === "status" && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 24px", padding: "8px 20px 16px" }}>
              <div>
                <h3 className="label-caps" style={{ margin: "12px 0 6px", fontSize: 12 }}>Attributes</h3>
                {sel.attrs.map(a => { const c = m.cols[a.name] ?? Object.entries(bindings).find(([, at]) => at === a.name)?.[0]; return (
                  <div key={a.name} style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", alignItems: "center", gap: 12, padding: "8px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}>
                    <span>{a.name}</span>
                    <span className="mono row" style={{ fontSize: 12, color: c ? "var(--ink)" : "#B84F00", gap: 6 }}><Dot color={c ? BLUE : ORANGE} />{c ?? "unmapped"}</span>
                    {editable && <span className="row" style={{ gap: 4 }}><Button size="xs" onClick={() => setPanel("data")}>{c ? "Change" : "Bind"}</Button><Button size="xs" variant="ghost" onClick={() => say(`${a.name} excluded`)}>Exclude</Button></span>}
                  </div>); })}
              </div>
              <div>
                <h3 className="label-caps" style={{ margin: "12px 0 6px", fontSize: 12 }}>Relationships</h3>
                {sel.rels.map(r => { const v = m.rels?.[r.name]; return (
                  <div key={r.name} style={{ display: "grid", gridTemplateColumns: "1fr 1.4fr auto", alignItems: "center", gap: 12, padding: "8px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}>
                    <span>{r.name} <span className="muted">→ {r.target}</span></span>
                    <span className="mono row" style={{ fontSize: 11.5, color: v ? "var(--ink)" : "#B84F00", gap: 6 }}><Dot color={v ? BLUE : ORANGE} />{v ?? "unmapped"}</span>
                    {editable && <Button size="xs" onClick={() => say(`Map ${r.name}: FK, link table or SQL`)}>Map</Button>}
                  </div>); })}
                {sel.rels.length === 0 && <p className="muted-2" style={{ fontSize: 12.5, margin: "8px 0" }}>No relationships from this class.</p>}
              </div>
            </div>
          )}
          {m && panel === "data" && (
            <>
              <div className="muted small" style={{ padding: "12px 20px 4px" }}>First 5 rows of <span className="mono">{tableText}</span>. {editable ? "Click a column header to bind it to an attribute." : "Bindings are shown as badges."}</div>
              {preview.error && <div style={{ padding: "0 20px 16px" }}><ErrorNotice error={preview.error} /></div>}
              {preview.loading && <div style={{ padding: "8px 20px 16px" }}><Skeleton h={120} /></div>}
              {preview.data && preview.data.columns.length > 0 && (
                <div style={{ overflowX: "auto", padding: "0 20px 16px" }}>
                  <div style={{ display: "grid", gridTemplateColumns: `repeat(${preview.data.columns.length},minmax(120px,1fr))`, minWidth: 600, border: "1px solid var(--line)", borderRadius: 8, overflow: "hidden" }}>
                    {preview.data.columns.map(c => { const isKey = c === m.key; const b = bound[c]; return (
                      <button key={c} type="button" title="Bind this column" disabled={!editable} onClick={() => { const attr = sel.attrs.find(a => !m.cols[a.name] && !Object.values(bindings).includes(a.name)); if (attr) { setBindings(bs => ({ ...bs, [c]: attr.name })); say(`${c} → ${attr.name}`); } else say("All attributes are bound"); }}
                        style={{ textAlign: "left", padding: "8px 10px", background: "var(--surface-3)", border: 0, borderBottom: "1px solid var(--line)", font: "500 11.5px var(--mono)", color: "var(--ink)", cursor: editable ? "pointer" : "default", display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                        {c}{(isKey || b) && <span className="pill mini" style={{ background: isKey ? BLUE : "var(--blue-soft)", color: isKey ? "#fff" : DARK, fontFamily: "var(--font)" }}>{isKey ? "ID" : b}</span>}
                      </button>); })}
                    {preview.data.rows.flatMap((r, i) => r.map((v, j) => <span key={`${i}-${j}`} style={{ padding: "7px 10px", borderTop: "1px solid var(--line-2)", fontSize: 12, color: v == null ? "#B3B3B7" : "var(--ink)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{v ?? "null"}</span>))}
                  </div>
                </div>
              )}
              {preview.data && preview.data.columns.length === 0 && <p className="muted" style={{ padding: "0 20px 16px" }}>Data preview is available for table-backed classes.</p>}
            </>
          )}
          {m && panel === "sql" && (
            <div style={{ padding: "16px 20px" }}>
              <div className="row between" style={{ marginBottom: 8 }}><span className="muted small">Compiled for the running adapter · <strong style={{ color: DARK, fontWeight: 600 }}>{dbx ? "Databricks" : "Postgres"}</strong> dialect</span><Button size="xs" style={{ height: 26 }} onClick={() => { navigator.clipboard?.writeText(sql.data ?? "").catch(() => {}); say("SQL copied"); }}><Icon name="copy" size={14} />Copy</Button></div>
              {sql.loading ? <Skeleton h={160} /> : <pre className="pre">{sql.data}</pre>}
            </div>
          )}
        </Card>
      )}
    </>
  );
}
