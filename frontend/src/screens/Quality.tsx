// Data quality: every table that carries rules, with its score, what passes and what does not, and
// which dimensions its rules cover; a table opens its own Data quality view. The graph constraints
// (SHACL-like checks over the built graph) keep their own tab.
import { useState } from "react";
import { Button, Card, Dot, Skeleton, Spinner, Tabs } from "@/components/ui";
import { useApp, useLoad } from "@/state/app";
import { useDomain, useGo, useParam } from "@/state/domain";
import { relTime } from "@/api/format";
import type { Constraint, DqTableSummary } from "@/api";

const short = (t: string) => t.split(".").pop() ?? t;
const schemaOf = (t: string) => { const p = t.split("."); return p.length >= 2 ? p[p.length - 2] : ""; };
const scoreColor = (s: number | null) => (s == null ? "var(--muted-3)" : s >= 0.95 ? "var(--blue)" : s >= 0.8 ? "#FF7000" : "#1B1B1C");

export function Quality() {
  const { api, say } = useApp();
  const { domain, version, editable } = useDomain();
  const go = useGo();
  const [view, setView] = useParam("view", "tables");
  const ov = useLoad(() => api.dqOverview(domain.name, version!.version), [domain.name, version?.version]);
  const [running, setRunning] = useState<string | null>(null);
  const tables = ov.data?.tables ?? [];
  const scored = tables.filter(t => t.score != null);
  const avg = scored.length ? scored.reduce((a, t) => a + (t.score ?? 0), 0) / scored.length : null;
  const failing = tables.reduce((a, t) => a + t.summary.failing + t.summary.error, 0);
  const warning = tables.reduce((a, t) => a + t.summary.warning, 0);
  const open = (t: DqTableSummary) => { const p = t.table.split("."); go("table", { schema: p.slice(0, -1).join("."), table: p[p.length - 1], tab: "dq" }); };
  const run = async (t: DqTableSummary) => {
    if (running) return; setRunning(t.table);
    try { await api.runDq(domain.name, version!.version, t.table); ov.reload(); say(`Rules of ${short(t.table)} run`); }
    catch (e) { say(e instanceof Error ? e.message : String(e)); }
    finally { setRunning(null); }
  };

  return (
    <>
      <div className="page-head">
        <div><h1>Data quality</h1><p>Where rules are applied in v{version?.version}, how each table scores, and what needs attention. Rules are added on a table or from the Rules tab.</p></div>
        <div className="actions">{view !== "graph" && <Button onClick={() => go("rules")}>Manage rules</Button>}</div>
      </div>
      <Tabs items={[{ id: "tables", label: "Tables", count: tables.length || false }, { id: "graph", label: "Graph constraints" }]} value={view === "graph" ? "graph" : "tables"} onChange={setView} />
      {view === "graph" ? <GraphConstraints editable={editable} /> : (
        <div style={{ display: "grid", gap: 16, marginTop: 16 }}>
          {ov.loading && !ov.data && <Skeleton h={120} />}
          {ov.data && (
            <div className="grid cols-4">
              {[["Tables with rules", String(tables.length), "var(--ink)"], ["Average score", avg == null ? "—" : `${(avg * 100).toFixed(0)}%`, scoreColor(avg)],
                ["Warnings", String(warning), warning ? "#B84F00" : "var(--ink)"], ["Failing", String(failing), failing ? "#1B1B1C" : "var(--ink)"]].map(([k, v, c]) => (
                <Card key={k} style={{ padding: "14px 16px" }}><div className="label-caps" style={{ fontSize: 10.5, color: "var(--muted-3)" }}>{k}</div><div style={{ fontSize: 24, fontWeight: 800, letterSpacing: "-.02em", color: c }}>{v}</div></Card>))}
            </div>
          )}
          {ov.data && tables.length === 0 && <Card className="dashed"><strong>No table has rules yet.</strong><p className="muted" style={{ marginTop: 6 }}>Open a table's Data quality view to derive rules from its profile, or add rules from the Rules tab.</p></Card>}
          {tables.map(t => (
            <Card key={t.table} className="dq-table" style={{ padding: "14px 18px", cursor: "pointer" }}>
              <div className="row between" style={{ gap: 16, alignItems: "flex-start" }} onClick={() => open(t)}>
                <div style={{ minWidth: 0 }}>
                  <div className="row" style={{ gap: 10 }}><strong style={{ fontSize: 15, fontWeight: 800 }}>{short(t.table)}</strong><span className="muted xs mono">{schemaOf(t.table)}</span></div>
                  <div className="muted small" style={{ marginTop: 2 }}>{t.rules} rule{t.rules === 1 ? "" : "s"}{t.enabled !== t.rules ? ` · ${t.enabled} enabled` : ""} · {t.last_run_at ? `run ${relTime(t.last_run_at)}` : "never run"}</div>
                  <div className="row" style={{ gap: 6, marginTop: 8, flexWrap: "wrap" }}>
                    {Object.entries(t.dimensions).map(([d, n]) => <span key={d} className="pill outline" style={{ fontSize: 11 }}>{d} · {n}</span>)}
                  </div>
                </div>
                <div className="row" style={{ gap: 18, flex: "none", alignItems: "center" }}>
                  <div className="row" style={{ gap: 10 }}>
                    {(["passing", "warning", "failing"] as const).map(k => <span key={k} className="row muted small" style={{ gap: 5 }} aria-label={`${k} rules`}><Dot color={k === "passing" ? "var(--blue)" : k === "warning" ? "#FF7000" : "#1B1B1C"} />{t.summary[k] + (k === "failing" ? t.summary.error : 0)}</span>)}
                  </div>
                  <div style={{ textAlign: "right", minWidth: 72 }} aria-label={`Score of ${short(t.table)}`}>
                    <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.02em", color: scoreColor(t.score) }}>{t.score == null ? "—" : `${(t.score * 100).toFixed(0)}%`}</div>
                    <div className="muted xs">score</div>
                  </div>
                  {editable && <Button size="sm" style={{ height: 30 }} disabled={running === t.table} onClick={e => { e.stopPropagation(); void run(t); }}>{running === t.table ? "Running…" : "Run"}</Button>}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}

/** SQL-validated constraints over the built graph; sample violators link into Explore. */
function GraphConstraints({ editable }: { editable: boolean }) {
  const { api, say } = useApp();
  const { domain, version } = useDomain();
  const go = useGo();
  const rows = useLoad(() => api.constraints(domain.name, version!.version), [domain.name, version?.version]);
  const [checked, setChecked] = useState<Constraint[] | null>(null);
  const [busy, setBusy] = useState<"derive" | "check" | null>(null);
  const run = async (what: "derive" | "check") => {
    setBusy(what);
    try {
      const out = what === "check" ? await api.runConstraintChecks(domain.name, version!.version) : await api.deriveConstraints(domain.name, version!.version);
      if (what === "check") { setChecked(out); const bad = out.reduce((a, c) => a + (c.count ?? 0), 0); say(`Checks run · ${bad} violation${bad === 1 ? "" : "s"} across ${out.length} constraint${out.length === 1 ? "" : "s"}`); }
      else { setChecked(null); rows.reload(); say(`${out.length} constraint${out.length === 1 ? "" : "s"} from the ontology`); }
    } catch (e) { say(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(null); }
  };
  const cols = "1.6fr 1fr 1fr .9fr .8fr 1.4fr";
  return (
    <div style={{ marginTop: 16 }}>
      <div className="row between" style={{ marginBottom: 12 }}><p className="muted">Constraints over the built graph, checked in SQL; sample violators link into Explore.</p>
        <div className="actions">{editable && <Button disabled={!!busy} onClick={() => void run("derive")}>{busy === "derive" && <Spinner />}Derive from ontology</Button>}<Button variant="primary" disabled={!!busy} onClick={() => void run("check")}>{busy === "check" && <Spinner />}Run checks</Button></div></div>
      <Card flush>
        <div className="grid-head" style={{ gridTemplateColumns: cols, padding: "10px 20px" }}><span>Constraint</span><span>Target</span><span>Kind</span><span>Severity</span><span>Violations</span><span>Sample</span></div>
        {rows.loading && <div style={{ padding: 20 }}><Skeleton h={16} /><Skeleton h={16} /></div>}
        {(checked ?? rows.data ?? []).map(q => (
          <div key={q.name} className="grid-row" style={{ gridTemplateColumns: cols }}>
            <span style={{ fontWeight: 600 }}>{q.name}</span><span>{q.target}</span><span className="mono" style={{ fontSize: 11.5 }}>{q.kind}</span>
            <span className="row"><Dot color={q.severity === "violation" ? "#FF7000" : "#B3B3B7"} />{q.severity}</span>
            <span style={{ fontWeight: 700, color: q.count ? "#B84F00" : "var(--ink)" }}>{q.count ?? "—"}</span>
            <a href="#" className="mono" style={{ fontSize: 11.5 }} onClick={e => { e.preventDefault(); go("explore", q.sampleEntity ? { entity: q.sampleEntity } : {}); }}>{q.sample ?? "not checked"}</a>
          </div>
        ))}
        {rows.data?.length === 0 && <p className="muted" style={{ padding: "12px 20px" }}>No constraint yet.</p>}
      </Card>
    </div>
  );
}
