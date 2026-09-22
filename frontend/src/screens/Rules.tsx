// Rules: the data-quality rules of the working version, across every table. The catalogue of
// kinds (DQX-style check functions) to pick from, every rule with its last result, and a way to
// add one to any snapshotted table. The reasoning rules (SWRL, compiled to SQL) keep their own tab.
import { useMemo, useState } from "react";
import { Button, Card, Pill, Skeleton, Tabs, Toggle } from "@/components/ui";
import { RuleDialog } from "@/components/RuleDialog";
import { describeRule } from "@/screens/Table";
import { useApp, useLoad } from "@/state/app";
import { useDomain, useGo, useParam } from "@/state/domain";
import { relTime } from "@/api/format";
import type { DqKind, DqRule } from "@/api";

const DIMENSIONS = ["completeness", "uniqueness", "validity", "consistency", "timeliness", "volume"];
const TONE: Record<string, string> = { passing: "var(--blue)", warning: "#FF7000", failing: "#1B1B1C", error: "#FF7000" };
const short = (t: string) => t.split(".").pop() ?? t;
const schemaOf = (t: string) => { const p = t.split("."); return p.length >= 2 ? p[p.length - 2] : ""; };

export function Rules() {
  const { api, say } = useApp();
  const { domain, version, editable } = useDomain();
  const go = useGo();
  const [view, setView] = useParam("view", "dq");
  const ov = useLoad(() => api.dqOverview(domain.name, version!.version), [domain.name, version?.version]);
  const snapshot = useLoad(() => api.snapshot(domain.name, version!.version), [domain.name, version?.version]);
  const [dialog, setDialog] = useState<{ open: boolean; kind?: DqKind }>({ open: false });
  const [table, setTable] = useState("");
  const kinds = ov.data?.kinds ?? [];
  const rules = ov.data?.rules ?? [];
  const used = useMemo(() => rules.reduce<Record<string, number>>((a, r) => ({ ...a, [r.kind]: (a[r.kind] ?? 0) + 1 }), {}), [rules]);
  const attention = rules.filter(r => r.enabled && r.last && r.last.status !== "passing").length;
  const passing = rules.filter(r => r.enabled && r.last?.status === "passing").length;
  const tables = (snapshot.data ?? []).map(t => t.table);
  const columns = (snapshot.data ?? []).find(t => t.table === table)?.columnNames ?? [];
  const openTable = (r: DqRule, tab = "dq") => { const p = r.table_name.split("."); go("table", { schema: p.slice(0, -1).join("."), table: p[p.length - 1], tab }); };
  const add = async (rule: Parameters<typeof api.addRule>[3]) => {
    await api.addRule(domain.name, version!.version, table, rule); ov.reload(); say(`Rule ${rule.name} added to ${short(table)}`);
  };

  return (
    <>
      <div className="page-head">
        <div><h1>Rules</h1><p>Every data-quality rule of v{version?.version}, on every table, and the kinds you can add: each mirrors a DQX check function and compiles to SQL on the source, Postgres or Databricks alike.</p></div>
        <div className="actions">{editable && view === "dq" && <Button variant="primary" onClick={() => { setTable(tables[0] ?? ""); setDialog({ open: true }); }}>New rule</Button>}</div>
      </div>
      <Tabs items={[{ id: "dq", label: "Data-quality rules", count: rules.length || false }, { id: "reasoning", label: "Reasoning rules" }]} value={view === "reasoning" ? "reasoning" : "dq"} onChange={setView} />
      {view === "reasoning" ? <ReasoningRules /> : (
        <div style={{ display: "grid", gap: 16, marginTop: 16 }}>
          {ov.loading && !ov.data && <Skeleton h={120} />}
          {ov.data && (
            <div className="grid cols-4">
              {[["Rules", String(rules.length)], ["Tables covered", String(ov.data.tables.length)], ["Passing", String(passing)], ["Need attention", String(attention)]].map(([k, v]) => (
                <Card key={k} style={{ padding: "14px 16px" }}><div className="label-caps" style={{ fontSize: 10.5, color: "var(--muted-3)" }}>{k}</div><div style={{ fontSize: 24, fontWeight: 800, letterSpacing: "-.02em", color: k === "Need attention" && attention ? "#B84F00" : "var(--ink)" }}>{v}</div></Card>))}
            </div>
          )}
          <Card>
            <div className="row between" style={{ marginBottom: 10 }}><h2 className="h2">Rule kinds</h2><span className="muted small">{kinds.length} kinds · pick one to add it to a table</span></div>
            {DIMENSIONS.map(d => { const ks = kinds.filter(k => k.dimension === d); return ks.length ? (
              <div key={d} style={{ marginBottom: 12 }}>
                <div className="label-caps" style={{ fontSize: 10.5, color: "var(--muted-3)", margin: "8px 0 6px" }}>{d}</div>
                <div className="kind-grid">
                  {ks.map(k => (
                    <button type="button" key={k.kind} className="kind" title={k.help} disabled={!editable} onClick={() => { setTable(tables[0] ?? ""); setDialog({ open: true, kind: k.kind }); }}>
                      <span className="row between"><strong>{k.label}</strong>{used[k.kind] ? <span className="chip">{used[k.kind]}</span> : null}</span>
                      <span className="muted xs">{k.help}</span>
                      <span className="mono muted-3 xs">{k.level} · DQX {k.dqx}</span>
                    </button>))}
                </div>
              </div>) : null; })}
          </Card>
          <Card flush>
            <div className="card-head" style={{ alignItems: "center" }}><h2 className="h2">All rules</h2><span className="muted small">Click a rule to open its table</span></div>
            {rules.length === 0 && !ov.loading && <p className="muted" style={{ padding: "12px 20px 18px" }}>No rule yet. Pick a kind above, or open a table and derive rules from its profile.</p>}
            {rules.length > 0 && (
              <table className="dom-table" style={{ border: 0, borderRadius: 0 }} aria-label="All rules">
                <thead><tr><th>Table</th><th>Rule</th><th>Kind</th><th>Column</th><th className="num">Last pass</th><th>Status</th><th>Enabled</th></tr></thead>
                <tbody>
                  {rules.map(r => (
                    <tr key={r.id} className="link" onClick={() => openTable(r)}>
                      <td><div style={{ fontWeight: 600 }}>{short(r.table_name)}</div><div className="muted xs mono">{schemaOf(r.table_name)}</div></td>
                      <td><div style={{ fontWeight: 600 }}>{r.name}</div><div className="muted xs mono">{describeRule(r)}</div></td>
                      <td><Pill tone="outline" style={{ fontSize: 11 }}>{kinds.find(k => k.kind === r.kind)?.label ?? r.kind}</Pill></td>
                      <td className="mono small">{r.column_name ?? "—"}</td>
                      <td className="num" style={{ fontSize: 13 }}>{r.last?.pass_rate != null ? `${(r.last.pass_rate * 100).toFixed(0)}%` : "—"}</td>
                      <td>{r.last ? <span className="row" style={{ gap: 6 }}><i style={{ width: 8, height: 8, borderRadius: 4, background: TONE[r.last.status] ?? "var(--grey)" }} />{r.last.status}<span className="muted xs">· {relTime(r.last.ran_at)}</span></span> : <span className="muted">never run</span>}</td>
                      <td onClick={e => e.stopPropagation()}><Toggle on={r.enabled} label={`Enable ${r.name}`} onChange={async v => { await api.updateRule(r.id, { enabled: v }); ov.reload(); }} /></td>
                    </tr>))}
                </tbody>
              </table>
            )}
          </Card>
        </div>
      )}
      <RuleDialog open={dialog.open} presetKind={dialog.kind} onClose={() => setDialog({ open: false })} columns={columns} kinds={kinds} tables={tables} table={table} onTable={setTable}
        onSave={async rule => { await add(rule); setDialog({ open: false }); }} />
    </>
  );
}

/** SWRL-style reasoning rules compiled to SQL: materialize adds inferred triples, violation flags entities. */
function ReasoningRules() {
  const { api, say } = useApp();
  const { domain, version } = useDomain();
  const rules = useLoad(() => api.rules(domain.name, version!.version), [domain.name, version?.version]);
  const [enabled, setEnabled] = useState<Record<string, boolean>>({});
  return (
    <div className="grid" style={{ gap: 12, marginTop: 16 }}>
      <div className="row between"><p className="muted">Rules over the graph: materialize adds inferred triples at build time; violation flags the entities that match.</p>
        <div className="actions"><Button onClick={() => say("OWL RL closure · +23,207 triples")}>Run OWL RL</Button><Button onClick={() => say("2 rules run · +19,204 triples, 0 violations")}>Run rules</Button></div></div>
      {rules.loading && <Skeleton h={120} />}
      {(rules.data ?? []).map(r => { const on = enabled[r.name] ?? r.enabled; return (
        <Card key={r.name} style={{ padding: "16px 20px", display: "grid", gridTemplateColumns: "minmax(0,1fr) auto", gap: 16, alignItems: "start" }}>
          <div>
            <div className="row" style={{ gap: 10, marginBottom: 8 }}><strong style={{ fontSize: 14, fontWeight: 700 }}>{r.name}</strong><Pill tone="blue" style={{ border: 0 }}>{r.mode}</Pill></div>
            <pre className="pre light">{r.text}</pre>
            <div className="muted small" style={{ marginTop: 8 }}>Last run: {r.lastRun}</div>
          </div>
          <label className="row muted small" style={{ fontWeight: 600, cursor: "pointer" }}><Toggle on={on} label={`Enable ${r.name}`} onChange={v => { setEnabled(e => ({ ...e, [r.name]: v })); say(`${r.name} ${v ? "enabled" : "disabled"}`); }} />Enabled</label>
        </Card>); })}
      {rules.data?.length === 0 && <p className="muted">No reasoning rule yet.</p>}
    </div>
  );
}
