// One table of the snapshot, three ways: its profile (rows, nulls, ranges), its data quality
// (rules, scores, history) and its glossary (business terms and KPI metrics that name it).
import { useEffect, useState, type ReactNode } from "react";
import { Button, Dialog, Dot, ErrorNotice, Label, Skeleton, Spinner } from "@/components/ui";
import { Icon } from "@/components/icons";
import { useApp, useLoad } from "@/state/app";
import { useDomain, useGo, useParam, useSetParams } from "@/state/domain";
import { relTime } from "@/api/format";
import type { AiProgress, DqKind, DqRule, DqStatus, GlossaryEntry, RuleInput, SnapshotTable, TableProfile, TermInput } from "@/api";

type Tab = "profile" | "dq" | "glossary";
const BLUE = "#2249FF", ORANGE = "#FF7000", GREY = "#B3B3B7";
const KINDS: { id: DqKind; label: string; dimension: string }[] = [
  { id: "not_null", label: "Not null", dimension: "completeness" }, { id: "unique", label: "Unique", dimension: "uniqueness" },
  { id: "in_set", label: "Value in allowed set", dimension: "validity" }, { id: "range", label: "Value within range", dimension: "validity" },
  { id: "regex", label: "Matches a pattern", dimension: "validity" }, { id: "referential", label: "Referential integrity", dimension: "consistency" },
  { id: "freshness", label: "Freshness", dimension: "timeliness" }, { id: "row_count", label: "Row count within range", dimension: "volume" },
  { id: "custom", label: "Custom predicate", dimension: "validity" }];
const STATUS_TONE: Record<string, string> = { passing: BLUE, warning: ORANGE, failing: "#1B1B1C", error: ORANGE };

const short = (full: string) => full.split(".").pop() ?? full;
const schemaOf = (full: string) => { const p = full.split("."); return p.length >= 2 ? p[p.length - 2] : ""; };
const fmtInt = (n: number | null | undefined) => (n == null ? "—" : n.toLocaleString());
const fmtBytes = (n: number | null | undefined) => (n == null ? "—" : n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : n >= 1e3 ? `${(n / 1e3).toFixed(0)} KB` : `${n} B`);
const pct = (x: number | null | undefined, digits = 0) => (x == null ? "—" : `${(x * 100).toFixed(digits)}%`);
const scoreColor = (s: number | null) => (s == null ? "var(--muted-3)" : s >= 0.95 ? BLUE : s >= 0.8 ? ORANGE : "var(--ink)");
const ago = (iso: string | null | undefined) => (iso ? relTime(iso) : "never");
export function describeRule(r: { kind: DqKind; column_name: string | null; params: Record<string, unknown> }): string {
  const c = r.column_name ?? "", p = r.params ?? {};
  switch (r.kind) {
    case "not_null": return `${c} is not null`;
    case "unique": return `count(distinct ${c}) = count(*)`;
    case "in_set": return `${c} in (${(p.values as unknown[] | undefined)?.join(", ") ?? ""})`;
    case "range": return `${c} between ${p.min ?? "−∞"} and ${p.max ?? "∞"}`;
    case "regex": return `${c} matches ${p.pattern ?? ""}`;
    case "referential": return `${c} in (select ${p.ref_column ?? "id"} from ${p.ref_table ?? "parent"})`;
    case "freshness": return `max(${c}) > now() - ${p.hours ?? 24}h`;
    case "row_count": return `count(*) between ${p.min ?? 0} and ${p.max ?? "∞"}`;
    default: return String(p.predicate ?? "");
  }
}

export function Table() {
  const { api, say } = useApp();
  const { domain, version, editable } = useDomain();
  const go = useGo();
  const [schema] = useParam("schema", "");
  const [table] = useParam("table", "");
  const [tab, setTab] = useParam("tab", "profile");
  const setParams = useSetParams();
  const snapshot = useLoad(() => version ? api.snapshot(domain.name, version.version) : Promise.resolve([] as SnapshotTable[]), [domain.name, version?.version]);
  const full = schema ? `${schema}.${table}` : table;
  const snap = (snapshot.data ?? []).find(t => t.table.toLowerCase() === full.toLowerCase()) ?? null;
  const tcls = useLoad(() => full ? api.tableClass(domain.name, full, version?.version) : Promise.resolve(null), [domain.name, full, version?.version]);
  const profile = useLoad(() => version && full ? api.tableProfile(domain.name, version.version, full) : Promise.resolve(null), [domain.name, version?.version, full]);
  const dq = useLoad(() => version && full ? api.tableDq(domain.name, version.version, full) : Promise.resolve(null), [domain.name, version?.version, full]);
  const glossary = useLoad(() => api.glossary(domain.name, { table: full }), [domain.name, full]);
  const cur = (tab as Tab) === "dq" || tab === "glossary" ? (tab as Tab) : "profile";
  const pickTable = (name: string) => { const p = name.split("."); setParams({ schema: p.slice(0, -1).join("."), table: p[p.length - 1] }); };

  return (
    <div className="tbl">
      <div className="tbl-head">
        <div className="tbl-title">
          <div className="muted small mono">{full}</div>
          <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
            <h1>{table || "Pick a table"}</h1>
            {tcls.data && <a href="#" className="pill blue lg" onClick={e => { e.preventDefault(); go("ontology", { cls: tcls.data!, view: "map" }); }}>{tcls.data}</a>}
          </div>
          <p className="muted">{schemaOf(full) ? `${schemaOf(full)} schema · ` : ""}{snap ? `${snap.columns} columns · in snapshot` : snapshot.loading ? "reading the snapshot…" : "not in the snapshot"}</p>
        </div>
        <div className="tbl-tabs" role="tablist" aria-label="Views">
          <button type="button" role="tab" className="tbl-tab" aria-selected={cur === "profile"} onClick={() => setTab("profile")}>Profile<span className="n">{snap ? `${snap.columns} cols` : "—"}</span></button>
          <button type="button" role="tab" className="tbl-tab" aria-selected={cur === "dq"} onClick={() => setTab("dq")}>Data quality<span className="n warn">{dq.data?.score != null ? pct(dq.data.score) : "—"}</span></button>
          <button type="button" role="tab" className="tbl-tab" aria-selected={cur === "glossary"} onClick={() => setTab("glossary")}>Glossary<span className="n">{glossary.data?.length ?? "—"}</span></button>
        </div>
        <label className="tbl-pick"><span className="muted small">Table</span>
          <select className="select" aria-label="Table" value={snap?.table ?? ""} onChange={e => pickTable(e.target.value)}>
            {!snap && <option value="">{full || "—"}</option>}
            {(snapshot.data ?? []).map(t => <option key={t.table} value={t.table}>{schemaOf(t.table) ? `${schemaOf(t.table)}.${short(t.table)}` : t.table}</option>)}
          </select>
        </label>
      </div>

      {!snap && !snapshot.loading && <div className="card dashed" style={{ marginTop: 8 }}><strong>{table ? `${table} is not in the snapshot of v${version?.version}.` : "No table chosen."}</strong><p className="muted" style={{ marginTop: 6 }}>Import it on the Metadata screen first; the profile, the rules and the glossary hang off the snapshot.</p><div style={{ marginTop: 12 }}><Button onClick={() => go("metadata", { schema, table })}>Open Metadata</Button></div></div>}

      {snap && cur === "profile" && <ProfileView profile={profile.data ?? null} loading={profile.loading} error={profile.error} snap={snap} dq={dq.data ?? null} editable={editable}
        onRun={async report => { const p = await api.runProfile(domain.name, version!.version, full, report); profile.reload(); dq.reload(); say(`Profile of ${table} updated · ${fmtInt(p.row_count)} rows`); }} />}
      {snap && cur === "dq" && <QualityView status={dq.data ?? null} loading={dq.loading} error={dq.error} snap={snap} editable={editable} reload={() => dq.reload()}
        run={async report => { await api.runDq(domain.name, version!.version, full, report); dq.reload(); say(`Rules of ${table} run`); }}
        suggest={async report => { const r = await api.suggestRules(domain.name, version!.version, full, report); dq.reload(); say(r.added ? `AI added ${r.added} rule${r.added === 1 ? "" : "s"}${r.skipped.length ? ` · ${r.skipped.length} skipped` : ""}` : "The AI proposed nothing new"); }}
        add={async rule => { await api.addRule(domain.name, version!.version, full, rule); dq.reload(); say(`Rule ${rule.name} added`); }}
        patch={async (id, p) => { await api.updateRule(id, p); dq.reload(); }} remove={async (r: DqRule) => { await api.deleteRule(r.id); dq.reload(); say(`Rule ${r.name} deleted`); }} />}
      {snap && cur === "glossary" && <GlossaryView entries={glossary.data ?? []} loading={glossary.loading} table={full} snap={snap} cls={tcls.data ?? null}
        add={async t => { await api.addTerm(domain.name, { ...t, table: full }); glossary.reload(); say(`${t.kind === "metric" ? "Metric" : "Term"} ${t.name} added`); }}
        patch={async (id, p) => { await api.updateTerm(id, p); glossary.reload(); }} remove={async e => { await api.deleteTerm(e.id); glossary.reload(); say(`${e.name} deleted`); }} />}
    </div>
  );
}

/** Wraps a long source-reading task: disables its button and shows the job's progress line. */
function useTask(fn: (report: (p: AiProgress) => void) => Promise<void>, say: (m: string) => void) {
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const start = async () => {
    if (busy) return;
    setBusy(true); setProgress("Starting…");
    try { await fn(p => setProgress(p.progress)); } catch (e) { say(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); setProgress(null); }
  };
  return { busy, progress, start };
}

// -- Profile --------------------------------------------------------------------------------------

function ProfileView({ profile, loading, error, snap, dq, editable, onRun }: { profile: TableProfile | null; loading: boolean; error: string | null; snap: SnapshotTable; dq: DqStatus | null; editable: boolean; onRun: (report: (p: AiProgress) => void) => Promise<void> }) {
  const { say } = useApp();
  const task = useTask(onRun, say);
  const [showAll, setShowAll] = useState(false);
  const [findings, setFindings] = useState(false);
  const colScore = Object.fromEntries((dq?.columns ?? []).map(c => [c.name.toLowerCase(), c.score]));
  const cols = profile?.columns ?? [];
  const nullable = cols.filter(c => c.nulls > 0).length;
  const nullRate = profile?.missing_cells ?? null;
  const rows = profile?.row_count ?? null;
  const sampled = rows != null && profile ? Math.round(rows * profile.sample_pct / 100) : null;
  const highCard = cols.filter(c => c.kind !== "date" && c.values.length === 0 && c.histogram.length === 0 && (c.unique_pct ?? 0) > 0.9).length;
  const listed = findings ? cols.filter(c => c.hints.length > 0) : cols;
  const cards = showAll ? listed : listed.slice(0, 24);
  const tiles: [string, string, string, string][] = profile ? [
    ["Rows", fmtInt(rows), profile.sample_pct < 100 ? `${fmtInt(sampled)} sampled` : "last profile", BLUE], ["Columns", String(cols.length), `${nullable} nullable`, BLUE],
    ["Null rate", pct(nullRate, 1), "across all cells", BLUE], ["Duplicates", profile.duplicate_rows == null ? "—" : fmtInt(profile.duplicate_rows), profile.duplicate_rows == null ? "not measured" : "identical rows", BLUE],
    ["Size", fmtBytes(profile.size_bytes), profile.size_bytes == null ? "not reported" : "in the warehouse", BLUE], ["Freshness", profile.last_modified ? relTime(profile.last_modified) : "—", profile.last_modified ? "since last write" : "not reported", ORANGE]] : [];
  return (
    <>
      {profile && <div className="tbl-tiles">{tiles.map(([k, v, sub, color]) => <div key={k} className="tile" aria-label={k}><span className="k">{k}<Dot color={color} /></span><b>{v}</b><span className="sub">{sub}</span><i /></div>)}</div>}
      {profile && (
        <section className="card tbl-card rowkey" aria-label="Row key">
          <span className="ic"><Icon name="check" size={12} /></span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="row" style={{ gap: 10, alignItems: "baseline" }}><h2>Row key</h2>{profile.row_key.length > 0 && <span className="mono" style={{ fontWeight: 700 }}>{profile.row_key.join(" + ")}</span>}</div>
            <p className="muted small" style={{ marginTop: 2 }}>The column(s) that identify each row, used to detect duplicates. {profile.row_key.length ? (snap.primaryKey.length ? "Declared in the catalog." : "Detected: unique and never null.") : "No single column identifies every row: rows may be genuine duplicates, or the key is composite."}{profile.duplicate_keys != null && profile.row_key.length ? ` ${fmtInt(profile.duplicate_keys)} duplicate key${profile.duplicate_keys === 1 ? "" : "s"}.` : ""}</p>
          </div>
        </section>
      )}
      <section className="card flush tbl-card" aria-label="Column summary">
        <div className="tbl-card-head">
          <div className="row" style={{ gap: 10, alignItems: "baseline" }}><h2>Column summary</h2><span className="muted small">{task.progress ?? (profile ? `Profiled ${ago(profile.profiled_at)} on a ${profile.sample_pct % 1 ? profile.sample_pct.toFixed(1) : profile.sample_pct}% sample` : loading ? "Reading…" : "Not profiled yet")}</span></div>
          <div className="row">
            {profile && <label className="row muted small" style={{ gap: 6 }}><input type="checkbox" checked={findings} onChange={e => setFindings(e.target.checked)} />Findings only ({cols.filter(c => c.hints.length).length})</label>}
            <Button variant="outline" pill disabled={!editable || task.busy} title={editable ? "Read the table again" : "Only the lease holder of a draft can profile"} onClick={task.start}>{task.busy && <Spinner blue />}{profile ? "Re-run profile" : "Run profile"}</Button>
          </div>
        </div>
        {error && <div style={{ padding: "0 20px 16px" }}><ErrorNotice error={error} /></div>}
        {loading && !profile && <div style={{ padding: 20 }}><Skeleton h={16} /><Skeleton h={16} style={{ marginTop: 10 }} /><Skeleton h={16} style={{ marginTop: 10 }} /></div>}
        {!loading && !profile && !error && <div className="tbl-empty"><strong>No profile of {short(snap.table)} yet.</strong><span className="muted">Run the profile to count rows, nulls, distinct values, ranges and distributions for its {snap.columns} columns.</span></div>}
        {profile && (
          <table className="prof" aria-label="Column summary">
            <colgroup><col style={{ width: "22%" }} /><col style={{ width: 84 }} /><col style={{ width: 104 }} /><col style={{ width: 80 }} /><col style={{ width: 120 }} /><col /><col /><col /><col /><col style={{ width: 56 }} /></colgroup>
            <thead><tr><th>Column</th><th>Role</th><th>Type</th><th style={{ textAlign: "right" }}>Missing</th><th style={{ textAlign: "right" }}>Unique</th><th style={{ textAlign: "right" }}>Min</th><th style={{ textAlign: "right" }}>Median</th><th style={{ textAlign: "right" }}>Mean</th><th style={{ textAlign: "right" }}>Max</th><th style={{ textAlign: "right" }}>DQ</th></tr></thead>
            <tbody>
              {listed.map(c => { const s = colScore[c.name.toLowerCase()]; const num = c.kind === "numeric" || c.kind === "numeric id"; return (
                <tr key={c.name}>
                  <td className="name" title={c.name}>{c.name}</td>
                  <td><span className={`role ${c.role.replace(" ", "-")}`}>{c.role}</span></td>
                  <td><span className={`kindtag ${c.kind.replace(" ", "-")}`}>{c.kind}</span></td>
                  <td className="num" style={{ color: c.null_rate > 0.05 ? "var(--orange-text)" : undefined }}>{pct(c.null_rate, c.null_rate > 0 && c.null_rate < 0.01 ? 1 : 0)}</td>
                  <td className="num">{fmtInt(c.distinct)}{c.unique_pct != null && <span className="muted-3"> ({c.unique_pct > 0 && c.unique_pct < 0.001 ? "<0.1" : (c.unique_pct * 100).toFixed(c.unique_pct >= 0.1 ? 0 : 1)}%)</span>}</td>
                  <td className="num">{c.min ?? "—"}</td><td className="num">{num ? fmtNum(c.median) : "—"}</td><td className="num">{num ? fmtNum(c.mean) : "—"}</td><td className="num">{c.max ?? "—"}</td>
                  <td className="num" style={{ fontWeight: 700, color: scoreColor(s ?? null) }}>{s == null ? "—" : pct(s)}</td>
                </tr>); })}
            </tbody>
          </table>
        )}
      </section>
      {profile && (
        <section aria-label="Column profiles">
          <div className="row between" style={{ alignItems: "baseline", flexWrap: "wrap", gap: 8, margin: "4px 0 10px" }}>
            <div><h2 className="h2">Column profiles</h2><p className="muted small">Per-column stats and distributions.{highCard ? ` Bar charts for ${highCard} high-cardinality column${highCard === 1 ? "" : "s"} are omitted: almost every value is distinct.` : ""}</p></div>
            <span className="muted small">Showing {cards.length} of {listed.length} columns{listed.length > cards.length ? ": use Show more for the rest." : "."}</span>
          </div>
          <div className="prof-grid">
            {cards.map(c => <ColumnCard key={c.name} c={c} />)}
          </div>
          {listed.length > cards.length && <div style={{ marginTop: 12 }}><Button onClick={() => setShowAll(true)}>Show more ({listed.length - cards.length})</Button></div>}
        </section>
      )}
    </>
  );
}

const fmtNum = (x: number | null | undefined, digits = 4) => (x == null ? "—" : Number.isInteger(x) ? x.toLocaleString() : x.toLocaleString(undefined, { maximumFractionDigits: digits }));
const fmtSigned = (x: number | null | undefined) => (x == null ? "—" : `${x > 0 ? "+" : ""}${fmtNum(x)}`);

function ColumnCard({ c }: { c: import("@/api").ColumnProfile }) {
  const num = c.kind === "numeric" || c.kind === "numeric id";
  const bars = c.values.length > 0 ? c.values.slice(0, 8).map(v => ({ label: v.value, n: v.n })) : c.histogram.length > 0 ? c.histogram.map(b => ({ label: `${fmtNum(b.lo, 2)} · ${fmtNum(b.hi, 2)}`, n: b.n })) : [];
  const max = Math.max(1, ...bars.map(b => b.n));
  const cell = (k: string, v: ReactNode, tone?: string) => <div className="stat"><span className="k">{k}</span><b style={{ color: tone }}>{v}</b></div>;
  return (
    <article className="pcard">
      <div className="row between" style={{ gap: 8, alignItems: "flex-start" }}><span className="pname" title={c.name}>{c.name}</span><span className="row" style={{ gap: 6, flex: "none" }}><span className={`role ${c.role.replace(" ", "-")}`}>{c.role}</span><span className={`kindtag ${c.kind.replace(" ", "-")}`}>{c.kind}</span></span></div>
      <div className="stats">
        {cell("Non-null", fmtInt(c.non_null))}{cell("Missing", <>{pct(c.null_rate, c.null_rate > 0 && c.null_rate < 0.01 ? 1 : 0)} <span className="muted-3">({fmtInt(c.nulls)})</span></>)}
        {cell("Unique", fmtInt(c.distinct))}{cell(num && !c.values.length ? "Mean" : "Mode", num && !c.values.length ? <>{fmtNum(c.mean)}{c.mean_ci != null && <span className="muted-2"> ± {fmtNum(c.mean_ci)}</span>}</> : c.top != null ? <>{c.top} <span className="muted-3">({c.top_share != null ? pct(c.top_share, c.top_share < 0.1 ? 1 : 0) : "—"})</span></> : "—")}
        {c.balance != null && cell("Balance", fmtNum(c.balance, 3))}
        {num && c.values.length > 0 && cell("Mean", <>{fmtNum(c.mean)}{c.mean_ci != null && <span className="muted-2"> ± {fmtNum(c.mean_ci)}</span>}</>)}
        {num && <>{cell("Std", fmtNum(c.std))}{cell("Median", fmtNum(c.median))}{cell("Skew", fmtSigned(c.skew))}{cell("Kurtosis", fmtSigned(c.kurtosis))}
          {cell("Outliers", pct(c.outlier_rate), (c.outlier_rate ?? 0) > 0.02 ? ORANGE : undefined)}{cell("Zeros", pct(c.zeros_rate, (c.zeros_rate ?? 0) > 0 && (c.zeros_rate ?? 0) < 0.01 ? 1 : 0))}
          {cell("Peaks", c.peaks ?? "—", (c.peaks ?? 0) >= 2 ? ORANGE : undefined)}{c.heaped_rate != null && (c.heaped_rate > 0.4) ? cell("Heaped", pct(c.heaped_rate, 1), ORANGE) : cell("Normal p", c.normal_p == null ? "—" : c.normal_p < 0.001 ? "0" : fmtNum(c.normal_p, 3), (c.normal_p ?? 1) < 0.05 ? ORANGE : undefined)}</>}
      </div>
      {bars.length > 0 ? (
        <div className={`chart ${c.values.length ? "cat" : "hist"}`} role="img" aria-label={`Distribution of ${c.name}`}>
          {bars.map(b => <div key={b.label} className="bar-row"><span className="lbl" title={b.label}>{b.label}</span><span className="track"><i style={{ width: `${Math.max(1.5, b.n / max * 100)}%` }} /></span><span className="cnt">{fmtInt(b.n)}</span></div>)}
        </div>
      ) : c.kind !== "date" && (c.unique_pct ?? 0) > 0.9 ? <p className="muted-2 small" style={{ fontStyle: "italic" }}>High cardinality: bar chart omitted (almost every value is distinct).</p> : null}
      {c.hints.length > 0 && <ul className="hints">{c.hints.map(h => <li key={h}>{h}</li>)}</ul>}
    </article>
  );
}

// -- Data quality -----------------------------------------------------------------------------------

type Filter = "all" | "passing" | "warning" | "failing";
function QualityView({ status, loading, error, snap, editable, reload, run, suggest, add, patch, remove }: {
  status: DqStatus | null; loading: boolean; error: string | null; snap: SnapshotTable; editable: boolean; reload: () => void;
  run: (report: (p: AiProgress) => void) => Promise<void>; suggest: (report: (p: AiProgress) => void) => Promise<void>;
  add: (rule: RuleInput) => Promise<void>; patch: (id: string, p: Partial<RuleInput>) => Promise<void>; remove: (r: DqRule) => Promise<void>;
}) {
  const { say } = useApp();
  const running = useTask(run, say);
  const asking = useTask(suggest, say);
  const [filter, setFilter] = useState<Filter>("all");
  const [dialog, setDialog] = useState(false);
  const rules = status?.rules ?? [];
  const shown = rules.filter(r => filter === "all" || r.last?.status === filter);
  const below = status ? status.summary.warning + status.summary.failing : 0;
  const history = status?.history ?? [];
  const weekAgo = history.length > 7 ? history[history.length - 8].score : null;
  const delta = status?.score != null && weekAgo != null ? status.score - weekAgo : null;
  const colStats = { failing: (status?.columns ?? []).filter(c => c.score != null && c.score < 0.8).length, warning: (status?.columns ?? []).filter(c => c.score != null && c.score >= 0.8 && c.score < 0.95).length };
  return (
    <>
      {error && <ErrorNotice error={error} />}
      {loading && !status && <Skeleton h={180} />}
      {status && (
        <div className="dq-top">
          <section className="dq-score" aria-label="Table score">
            <div className="k">Table score</div>
            <div className="row" style={{ gap: 14, alignItems: "baseline", flexWrap: "wrap" }}><b>{status.score == null ? "—" : pct(status.score)}</b>{delta != null && <span className="delta">{delta < 0 ? "▼" : delta > 0 ? "▲" : "▬"} {(Math.abs(delta) * 100).toFixed(1)} vs last week</span>}</div>
            <div className="sub">{status.score == null ? "No run yet: add rules and run them." : `${below} of ${rules.filter(r => r.enabled).length} rules below threshold · last run ${ago(status.last_run?.finished_at ?? status.last_run?.started_at)}`}</div>
            <div className="bars" aria-label="Score history">{Array.from({ length: 14 }, (_, i) => history[history.length - 14 + i] ?? null).map((h, i) => <span key={i} className={i === 13 ? "today" : ""} title={h ? `${h.started_at.slice(0, 10)} · ${pct(h.score)}` : "no run"} style={{ height: h?.score != null ? `${Math.max(8, h.score * 100)}%` : "8%", opacity: h ? 1 : 0.35 }} />)}</div>
            <div className="row between muted-2" style={{ fontSize: 11 }}><span>{history.length > 1 ? `${history.length} runs` : "14 days ago"}</span><span>Today</span></div>
          </section>
          <section className="card tbl-card" aria-label="Column scores">
            <div className="row between" style={{ alignItems: "baseline", marginBottom: 10 }}><h2>Column scores</h2><span className="muted small">{colStats.failing} failing · {colStats.warning} warning</span></div>
            <div className="col-scores">{status.columns.map(c => <div key={c.name} className="col-score" title={c.source === "rules" ? "Mean pass rate of its rules" : c.source === "profile" ? "Completeness from the profile" : "No rule and no profile"}><span className="row between"><span className="nm">{c.name}</span><b style={{ color: scoreColor(c.score) }}>{c.score == null ? "—" : pct(c.score)}</b></span><span className="bar"><i style={{ width: `${(c.score ?? 0) * 100}%`, background: scoreColor(c.score) }} /></span></div>)}</div>
          </section>
        </div>
      )}
      <section className="card flush tbl-card" aria-label="Rules">
        <div className="tbl-card-head" style={{ flexWrap: "wrap" }}>
          <div className="row" style={{ gap: 14 }}>
            <h2>Rules</h2>
            <div className="seg" role="tablist" aria-label="Rule filter">{(["all", "passing", "warning", "failing"] as Filter[]).map(f => <button key={f} type="button" role="tab" aria-selected={filter === f} onClick={() => setFilter(f)}>{f === "all" ? "All" : f[0].toUpperCase() + f.slice(1)}<span className="n">{f === "all" ? rules.length : status?.summary[f] ?? 0}</span></button>)}</div>
          </div>
          <div className="row">
            {(running.progress || asking.progress) && <span className="muted small">{running.progress ?? asking.progress}</span>}
            <Button variant="outline" pill disabled={!editable || asking.busy} onClick={asking.start}>{asking.busy ? <Spinner blue /> : <Icon name="ask" size={12} />}Suggest rules with AI</Button>
            <Button variant="outline" pill disabled={!editable} onClick={() => setDialog(true)}>+ New rule</Button>
            <Button variant="primary" pill disabled={!editable || running.busy || rules.every(r => !r.enabled)} onClick={running.start}>{running.busy && <Spinner />}Run all rules</Button>
          </div>
        </div>
        {rules.length === 0 && !loading && <div className="tbl-empty"><strong>No rule on {short(snap.table)} yet.</strong><span className="muted">Add one, or let the AI propose rules from the columns{status?.columns.length ? " and the profile" : ""}.</span></div>}
        {rules.length > 0 && (
          <table className="rules" aria-label="Rules">
            <colgroup><col /><col style={{ width: "18%" }} /><col style={{ width: "14%" }} /><col style={{ width: 70 }} /><col style={{ width: "14%" }} /><col style={{ width: 110 }} /><col style={{ width: 40 }} /></colgroup>
            <thead><tr><th>Rule</th><th>Column</th><th>Dimension</th><th style={{ textAlign: "right" }}>Pass</th><th>Owner</th><th>Status</th><th /></tr></thead>
            <tbody>
              {shown.map(r => { const st = r.last?.status ?? (r.enabled ? "not run" : "disabled"); return (
                <tr key={r.id} className={r.enabled ? "" : "off"}>
                  <td><div className="rname">{r.name}{r.origin === "ai" && <span className="pill mini" title="Proposed by the AI">AI</span>}</div><div className="rdesc mono" title={r.last?.error ?? undefined}>{r.last?.error ? r.last.error : describeRule(r)}</div></td>
                  <td className="mono small">{r.column_name ?? "—"}</td>
                  <td className="cap">{r.dimension}</td>
                  <td className="num" style={{ fontWeight: 700, color: r.last?.pass_rate == null ? "var(--muted-3)" : scoreColor(r.last.pass_rate) }}>{r.last?.pass_rate == null ? "—" : pct(r.last.pass_rate)}</td>
                  <td className="muted">{r.owner ?? "—"}</td>
                  <td><span className={`status-pill ${st}`}><Dot color={STATUS_TONE[st] ?? GREY} />{st[0].toUpperCase() + st.slice(1)}</span></td>
                  <td><RuleMenu rule={r} editable={editable} onToggle={() => patch(r.id, { enabled: !r.enabled })} onDelete={() => remove(r)} /></td>
                </tr>); })}
              {shown.length === 0 && <tr><td colSpan={7} className="muted" style={{ padding: 16 }}>No rule is {filter} right now.</td></tr>}
            </tbody>
          </table>
        )}
      </section>
      <RuleDialog open={dialog} onClose={() => setDialog(false)} columns={snap.columnNames} onSave={async rule => { await add(rule); setDialog(false); reload(); }} />
    </>
  );
}

function RuleMenu({ rule, editable, onToggle, onDelete }: { rule: DqRule; editable: boolean; onToggle: () => void; onDelete: () => void }) {
  const [open, setOpen] = useState(false);
  useEffect(() => { if (!open) return; const h = () => setOpen(false); window.addEventListener("click", h); return () => window.removeEventListener("click", h); }, [open]);
  return (
    <span style={{ position: "relative" }}>
      <button type="button" className="chip-act" aria-label={`Actions for ${rule.name}`} disabled={!editable} onClick={e => { e.stopPropagation(); setOpen(o => !o); }}>⋯</button>
      {open && <span className="menu" role="menu"><button type="button" role="menuitem" onClick={onToggle}>{rule.enabled ? "Disable rule" : "Enable rule"}</button><button type="button" role="menuitem" className="danger" onClick={onDelete}>Delete rule</button></span>}
    </span>
  );
}

function RuleDialog({ open, onClose, columns, onSave }: { open: boolean; onClose: () => void; columns: string[]; onSave: (r: RuleInput) => Promise<void> }) {
  const { say } = useApp();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<DqKind>("not_null");
  const [column, setColumn] = useState(columns[0] ?? "");
  const [p, setP] = useState<Record<string, string>>({});
  const [threshold, setThreshold] = useState("0.95");
  const [owner, setOwner] = useState("");
  const [busy, setBusy] = useState(false);
  const needsColumn = kind !== "row_count" && kind !== "custom";
  const params = (): Record<string, unknown> => {
    switch (kind) {
      case "in_set": return { values: (p.values ?? "").split(",").map(s => s.trim()).filter(Boolean) };
      case "range": case "row_count": return { ...(p.min ? { min: Number(p.min) } : {}), ...(p.max ? { max: Number(p.max) } : {}) };
      case "regex": return { pattern: p.pattern ?? "" };
      case "freshness": return { hours: Number(p.hours || 24) };
      case "referential": return { ref_table: p.ref_table ?? "", ref_column: p.ref_column ?? "" };
      case "custom": return { predicate: p.predicate ?? "" };
      default: return {};
    }
  };
  const field = (key: string, label: string, placeholder = "", mono = true) => <div><Label>{label}</Label><input className={`input full ${mono ? "mono" : ""}`} aria-label={label} placeholder={placeholder} value={p[key] ?? ""} onChange={e => setP(x => ({ ...x, [key]: e.target.value }))} /></div>;
  const submit = async () => {
    setBusy(true);
    try { await onSave({ name: name.trim() || `${KINDS.find(k => k.id === kind)?.label} on ${column}`, kind, column: needsColumn ? column : null, params: params(), threshold: Number(threshold) || 0.95, owner: owner.trim() || null }); setName(""); setP({}); }
    catch (e) { say(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  return (
    <Dialog title="New rule" open={open} onClose={onClose} width={520} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={busy || (needsColumn && !column)} onClick={submit}>{busy && <Spinner />}Add rule</Button></>}>
      <div style={{ display: "grid", gap: 12 }}>
        <div><Label>Name</Label><input className="input full" aria-label="Rule name" placeholder="What the rule checks" value={name} onChange={e => setName(e.target.value)} /></div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div><Label>Kind</Label><select className="select full" aria-label="Kind" value={kind} onChange={e => setKind(e.target.value as DqKind)}>{KINDS.map(k => <option key={k.id} value={k.id}>{k.label}</option>)}</select></div>
          {needsColumn && <div><Label>Column</Label><select className="select full mono" aria-label="Column" value={column} onChange={e => setColumn(e.target.value)}>{columns.map(c => <option key={c} value={c}>{c}</option>)}</select></div>}
        </div>
        {kind === "in_set" && field("values", "Allowed values (comma-separated)", "A, B, C")}
        {(kind === "range" || kind === "row_count") && <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>{field("min", "Minimum", "0")}{field("max", "Maximum", "")}</div>}
        {kind === "regex" && field("pattern", "Pattern (regular expression)", "^[A-Z]{2}$")}
        {kind === "freshness" && field("hours", "Fresh within (hours)", "24")}
        {kind === "referential" && <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>{field("ref_table", "Referenced table", "schema.table")}{field("ref_column", "Referenced column", "id")}</div>}
        {kind === "custom" && field("predicate", "SQL predicate (true for a good row)", "amount >= 0 AND currency IS NOT NULL")}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div><Label>Pass threshold (0 to 1)</Label><input className="input full mono" aria-label="Threshold" value={threshold} onChange={e => setThreshold(e.target.value)} /></div>
          <div><Label>Owner</Label><input className="input full" aria-label="Owner" placeholder="Domain steward" value={owner} onChange={e => setOwner(e.target.value)} /></div>
        </div>
      </div>
    </Dialog>
  );
}

// -- Glossary ---------------------------------------------------------------------------------------

function GlossaryView({ entries, loading, table, snap, cls, add, patch, remove }: { entries: GlossaryEntry[]; loading: boolean; table: string; snap: SnapshotTable; cls: string | null; add: (t: TermInput) => Promise<void>; patch: (id: string, p: Partial<TermInput>) => Promise<void>; remove: (e: GlossaryEntry) => Promise<void> }) {
  const [kind, setKind] = useParam("kind", "terms");
  const [q, setQ] = useState("");
  const [dialog, setDialog] = useState<"term" | "metric" | null>(null);
  const isMetric = kind === "metrics";
  const t = q.trim().toLowerCase();
  const terms = entries.filter(e => e.kind === "term"), metrics = entries.filter(e => e.kind === "metric");
  const shown = (isMetric ? metrics : terms).filter(e => !t || [e.name, e.definition, e.formula ?? "", e.class_name ?? "", ...e.columns].join(" ").toLowerCase().includes(t));
  return (
    <>
      <div className="gl-bar">
        <div className="seg" role="tablist" aria-label="Glossary kind">
          <button type="button" role="tab" aria-selected={!isMetric} onClick={() => setKind("terms")}>Business terms<span className="n">{terms.length}</span></button>
          <button type="button" role="tab" aria-selected={isMetric} onClick={() => setKind("metrics")}>KPI metrics<span className="n">{metrics.length}</span></button>
        </div>
        <div className="search-wrap" style={{ maxWidth: 420 }}><Icon name="search" stroke="#7A7A80" /><input aria-label={isMetric ? "Search metrics" : "Search terms"} className="input" placeholder={isMetric ? "Search metrics or formulas" : "Search terms, definitions, columns"} value={q} onChange={e => setQ(e.target.value)} /></div>
        <span className="spacer" />
        <Button variant="outline" pill onClick={() => setDialog(isMetric ? "metric" : "term")}>{isMetric ? "+ New metric" : "+ New term"}</Button>
      </div>
      {loading && entries.length === 0 && <Skeleton h={120} />}
      {!loading && shown.length === 0 && <div className="card dashed"><strong>{t ? `Nothing matches “${q}”.` : isMetric ? `No KPI metric names ${short(table)} yet.` : `No business term names ${short(table)} yet.`}</strong><p className="muted" style={{ marginTop: 6 }}>{isMetric ? "A metric is a formula over this table with a unit, a cadence and an owner." : "A term explains what a row or a column means to the business."}</p></div>}
      {!isMetric && shown.length > 0 && (
        <div className="term-grid">
          {shown.map(e => (
            <article key={e.id} className="term">
              <div className="row" style={{ gap: 8, alignItems: "flex-start", flexWrap: "wrap" }}><h3>{e.name}</h3>{e.schema_name && <span className="pill blue">{e.schema_name}</span>}<span className={`pill mini st ${e.status}`} style={{ marginLeft: "auto" }}><Dot color={e.status === "draft" ? ORANGE : BLUE} />{e.status[0].toUpperCase() + e.status.slice(1)}</span></div>
              <p>{e.definition || <span className="muted-3">No definition yet.</span>}</p>
              <div className="chips">{e.columns.map(c => <span key={c} className="pill mono">{c}</span>)}{e.class_name && <span className="pill outline">class {e.class_name}</span>}</div>
              <div className="foot"><span>Steward · {e.owner ?? "—"}</span><span>Updated {relTime(e.updated_at)}</span><EntryMenu entry={e} onApprove={() => patch(e.id, { status: e.status === "approved" ? "draft" : "approved" })} onDelete={() => remove(e)} /></div>
            </article>))}
        </div>
      )}
      {isMetric && shown.length > 0 && (
        <section className="card flush tbl-card">
          <table className="metrics" aria-label="KPI metrics">
            <colgroup><col style={{ width: "24%" }} /><col /><col style={{ width: 80 }} /><col style={{ width: 110 }} /><col style={{ width: "16%" }} /><col style={{ width: 110 }} /><col style={{ width: 40 }} /></colgroup>
            <thead><tr><th>Metric</th><th /><th>Unit</th><th /><th>Owner</th><th /><th /></tr></thead>
            <tbody>
              {shown.map(e => (
                <tr key={e.id}>
                  <td><div className="rname">{e.name}</div><div className="muted-2 small">{e.definition}</div></td>
                  <td><code className="formula">{e.formula || "—"}</code></td>
                  <td className="muted">{e.unit ?? "—"}</td>
                  <td className="muted">{e.frequency ?? "—"}</td>
                  <td className="muted">{e.owner ?? "—"}</td>
                  <td><span className={`status-pill st ${e.status}`}><Dot color={e.status === "certified" || e.status === "approved" ? BLUE : GREY} />{e.status[0].toUpperCase() + e.status.slice(1)}</span></td>
                  <td><EntryMenu entry={e} onApprove={() => patch(e.id, { status: e.status === "certified" ? "pending" : "certified" })} onDelete={() => remove(e)} /></td>
                </tr>))}
            </tbody>
          </table>
        </section>
      )}
      <TermDialog kind={dialog} onClose={() => setDialog(null)} columns={snap.columnNames} cls={cls} onSave={async t => { await add(t); setDialog(null); }} />
    </>
  );
}

function EntryMenu({ entry, onApprove, onDelete }: { entry: GlossaryEntry; onApprove: () => void; onDelete: () => void }) {
  const [open, setOpen] = useState(false);
  useEffect(() => { if (!open) return; const h = () => setOpen(false); window.addEventListener("click", h); return () => window.removeEventListener("click", h); }, [open]);
  const next = entry.kind === "metric" ? (entry.status === "certified" ? "Mark pending" : "Certify") : (entry.status === "approved" ? "Back to draft" : "Approve");
  return (
    <span style={{ position: "relative", marginLeft: "auto" }}>
      <button type="button" className="chip-act" aria-label={`Actions for ${entry.name}`} onClick={e => { e.stopPropagation(); setOpen(o => !o); }}>⋯</button>
      {open && <span className="menu" role="menu"><button type="button" role="menuitem" onClick={onApprove}>{next}</button><button type="button" role="menuitem" className="danger" onClick={onDelete}>Delete</button></span>}
    </span>
  );
}

function TermDialog({ kind, onClose, columns, cls, onSave }: { kind: "term" | "metric" | null; onClose: () => void; columns: string[]; cls: string | null; onSave: (t: TermInput) => Promise<void> }) {
  const { say } = useApp();
  const [f, setF] = useState<Record<string, string>>({});
  const [cols, setCols] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const v = (k: string) => f[k] ?? "";
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setF(x => ({ ...x, [k]: e.target.value }));
  const submit = async () => {
    if (!kind) return;
    setBusy(true);
    try {
      await onSave(kind === "metric"
        ? { kind, name: v("name"), definition: v("definition"), formula: v("formula"), unit: v("unit") || null, frequency: v("frequency") || null, owner: v("owner") || null, status: (v("status") || "pending") as TermInput["status"], columns: cols }
        : { kind, name: v("name"), definition: v("definition"), owner: v("owner") || null, status: (v("status") || "draft") as TermInput["status"], columns: cols, class_name: v("class_name") || cls });
      setF({}); setCols([]);
    } catch (e) { say(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const input = (k: string, label: string, placeholder = "", mono = false) => <div><Label>{label}</Label><input className={`input full ${mono ? "mono" : ""}`} aria-label={label} placeholder={placeholder} value={v(k)} onChange={set(k)} /></div>;
  return (
    <Dialog title={kind === "metric" ? "New KPI metric" : "New business term"} open={kind != null} onClose={onClose} width={560}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={busy || !v("name").trim()} onClick={submit}>{busy && <Spinner />}{kind === "metric" ? "Add metric" : "Add term"}</Button></>}>
      <div style={{ display: "grid", gap: 12 }}>
        {input("name", "Name", kind === "metric" ? "Headcount" : "Employee")}
        <div><Label>{kind === "metric" ? "Description" : "Definition"}</Label><textarea className="textarea full" aria-label={kind === "metric" ? "Description" : "Definition"} rows={3} placeholder={kind === "metric" ? "Active employees at period end" : "What this means to the business"} value={v("definition")} onChange={set("definition")} /></div>
        {kind === "metric" && input("formula", "Formula", "count(*) where CurrentFlag = true", true)}
        {kind === "metric" && <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>{input("unit", "Unit", "people")}{input("frequency", "Frequency", "Monthly")}</div>}
        <div><Label>Columns</Label><div className="chips" role="group" aria-label="Columns">{columns.map(c => <label key={c} className={`pill outline mono pick ${cols.includes(c) ? "on" : ""}`}><input type="checkbox" checked={cols.includes(c)} onChange={() => setCols(x => x.includes(c) ? x.filter(y => y !== c) : [...x, c])} />{c}</label>)}</div></div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          {input("owner", kind === "metric" ? "Owner" : "Steward", "HR analytics")}
          <div><Label>Status</Label><select className="select full" aria-label="Status" value={v("status") || (kind === "metric" ? "pending" : "draft")} onChange={set("status")}>{["draft", "pending", "approved", "certified"].map(s => <option key={s} value={s}>{s[0].toUpperCase() + s.slice(1)}</option>)}</select></div>
        </div>
        {kind === "term" && input("class_name", "Ontology class", cls ?? "Class name")}
      </div>
    </Dialog>
  );
}

export function TileRow({ children }: { children: ReactNode }) { return <div className="tbl-tiles">{children}</div>; }
