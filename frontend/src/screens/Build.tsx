import { useEffect, useRef, useState } from "react";
import { Button, Card, CheckDot, Dot, KV, Skeleton, Spinner } from "@/components/ui";
import { Icon } from "@/components/icons";
import { useApp, useLoad } from "@/state/app";
import { useDomain, useGo } from "@/state/domain";
import type { BuildRun } from "@/api";

const BLUE = "#2249FF", ORANGE = "#FF7000";
const RUN_DOT: Record<string, string> = { succeeded: BLUE, failed: ORANGE, cancelled: "#B3B3B7", running: ORANGE, queued: "#CFCFD2" };

export function Build() {
  const { api, config, say } = useApp();
  const { domain, version, editable } = useDomain();
  const go = useGo();
  const dbx = config.sourceKind === "databricks";
  const history = useLoad(() => api.builds(domain.name, version!.version), [domain.name, version?.version]);
  const checklist = useLoad(() => api.checklist(domain.name, version!.version), [domain.name, version?.version]);
  const [live, setLive] = useState<BuildRun | null>(null);
  const [lost, setLost] = useState<string | null>(null);
  const poll = useRef<ReturnType<typeof setInterval>>();

  // A build still running when the screen opens (reload mid-build) is picked up and polled.
  useEffect(() => { const r = history.data?.[0]; if (r && (r.status === "running" || r.status === "queued") && !live) setLive(r); }, [history.data]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Poll the run until it settles (GET /builds/{id}); give up after three failed reads and say so.
  useEffect(() => {
    if (!live || (live.status !== "running" && live.status !== "queued")) { clearInterval(poll.current); return; }
    let failures = 0, busy = false;
    poll.current = setInterval(async () => {
      if (busy) return; busy = true;
      try {
        const r = await api.buildStatus(live.id);
        failures = 0; setLive(r);
        if (r.status !== "running" && r.status !== "queued") { clearInterval(poll.current); history.reload(); say(r.status === "succeeded" ? `Build succeeded · ${r.triples} triples` : r.status === "failed" ? `Build failed · ${r.error}` : `Build ${r.status}`); }
      } catch (e) {
        if (++failures >= 3) { clearInterval(poll.current); setLost(e instanceof Error ? e.message : String(e)); setLive(null); history.reload(); }
      } finally { busy = false; }
    }, 500);
    return () => clearInterval(poll.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live?.id, live?.status]);

  const runs = history.data ?? [];
  const shown = live ?? runs[0] ?? null;
  const building = shown?.status === "running" || shown?.status === "queued";
  const built = shown?.status === "succeeded";
  const start = async () => { setLost(null); try { setLive(await api.startBuild(domain.name, version!.version)); } catch (e) { say(e instanceof Error ? e.message : String(e)); } };
  const cancel = async () => { if (live) { try { setLive(await api.cancelBuild(live.id)); } catch (e) { say(e instanceof Error ? e.message : String(e)); } } };
  const blockReason = editable ? "" : "Only the lease holder can build a draft";

  return (
    <>
      <div className="page-head">
        <div><h1>Build</h1><p>Compile the mapping to SQL, load triples from {dbx ? "Databricks" : "Postgres"}, infer, run rules and quality, publish. A failed build keeps the previous graph.</p></div>
        <div className="actions">
          {building && <Button onClick={cancel}>Cancel</Button>}
          <Button variant="primary" disabled={building || !editable} title={blockReason} onClick={start}>{building && <Spinner />}{building ? "Building…" : "Start build"}</Button>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 320px", gap: 20, alignItems: "start" }}>
        <div className="grid">
          <Card>
            <div className="row between" style={{ alignItems: "baseline", marginBottom: 12 }}><h2 className="h2">{building ? "Run in progress" : shown ? `Last run · ${shown.label ?? shown.id}` : "No build yet"}</h2><span className="mono muted small">{building && shown ? `step ${shown.stepIndex + 1} of ${shown.steps.length}` : shown ? `${shown.actor} · ${shown.duration}` : ""}</span></div>
            {lost && <div className="notice error" style={{ marginBottom: 12 }}><div className="row" style={{ fontWeight: 700, color: "var(--orange)" }}><Dot color={ORANGE} size={8} />Lost track of the build: {lost}</div><div className="muted xs" style={{ marginTop: 4 }}>The build keeps running on the server; the history below refreshes when you reload.</div></div>}
            {history.loading && !shown && <Skeleton h={90} />}
            {shown && (
              <div role="status" aria-live="polite" style={{ display: "grid", gridTemplateColumns: `repeat(${shown.steps.length},minmax(0,1fr))`, gap: 8 }}>
                {shown.steps.map(s => { const running = s.state === "running"; const done = s.state === "done"; return (
                  <div key={s.name} style={{ padding: 12, borderRadius: 8, border: `1px solid ${running ? ORANGE : "var(--line)"}`, background: "#fff" }}>
                    <div className="row" style={{ gap: 6, fontSize: 12, fontWeight: 700, color: done || running ? "var(--ink)" : "var(--muted-2)" }}><span style={{ width: 14, height: 14, borderRadius: "50%", background: done ? BLUE : running ? ORANGE : "#CFCFD2", display: "inline-flex", alignItems: "center", justifyContent: "center", flex: "none", animation: running ? "dg-pulse 1s ease-in-out infinite" : "none" }}>{done && <Icon name="check" size={10} stroke="#fff" width={2} />}</span>{s.name}</div>
                    <div className="mono muted small" style={{ marginTop: 6 }}>{s.seconds != null ? `${s.seconds.toFixed(1)} s` : running ? "…" : "—"}</div>
                    <div className="muted-2" style={{ fontSize: 11, marginTop: 2 }}>{done ? s.detail : running ? "running…" : "queued"}</div>
                  </div>); })}
              </div>
            )}
            {built && shown && <div className="row" style={{ marginTop: 14, alignItems: "baseline", gap: 10 }}><span style={{ fontSize: 32, fontWeight: 800, letterSpacing: "-.02em", color: BLUE }}>{shown.triples}</span><span className="muted">triples · <strong style={{ fontWeight: 600, color: "var(--ink)" }}>{shown.inferred}</strong> inferred</span></div>}
            {shown?.status === "failed" && <div className="notice error"><div className="row" style={{ fontWeight: 700, color: "var(--orange)" }}><Dot color={ORANGE} size={8} />Build failed</div><div className="mono xs" style={{ marginTop: 4, color: "var(--ink-2)" }}>{shown.error}</div></div>}
          </Card>
          <Card flush>
            <div className="card-head"><h2 className="h2">Run history</h2></div>
            <div className="grid-head" style={{ gridTemplateColumns: ".8fr 1fr .8fr .8fr 1fr 2fr" }}><span>Run</span><span>Status</span><span>Actor</span><span>Duration</span><span>Triples</span><span>Error</span></div>
            {runs.map(r => (
              <div key={r.id} className="grid-row" style={{ gridTemplateColumns: ".8fr 1fr .8fr .8fr 1fr 2fr" }}>
                <span className="mono small" title={r.id}>{r.label ?? r.id}</span><span className="row"><Dot color={RUN_DOT[r.status]} />{r.status}</span><span>{r.actor}</span><span className="mono small">{r.duration}</span><span className="mono small">{r.triples}</span><span className="small" style={{ color: "#B84F00" }}>{r.error}</span>
              </div>
            ))}
            {runs.length === 0 && !history.loading && <p className="muted" style={{ padding: 20 }}>No runs yet.</p>}
          </Card>
        </div>
        <div className="grid">
          <Card>
            <h2 className="h2" style={{ marginBottom: 10 }}>Pre-build checklist</h2>
            {(checklist.data ?? []).map(c => <a key={c.label} href="#" className="row" style={{ gap: 10, padding: "9px 0", borderTop: "1px solid var(--line-2)", color: "var(--ink)", fontSize: 12.5 }} onClick={e => { e.preventDefault(); go(c.go.screen, c.go.arg ? (c.go.screen === "ontology" ? { view: c.go.arg } : { table: c.go.arg }) : {}); }}><CheckDot ok={c.ok} /><span style={{ flex: 1 }}>{c.label}</span><span className="muted small">{c.value}</span></a>)}
          </Card>
          <Card>
            <h2 className="h2" style={{ marginBottom: 10 }}>Warehouse publish</h2>
            <KV k="Adapter" v={config.sourceKind} /><KV k="Materialization" v={dbx ? domain.materialization : "view"} /><KV k="Target schema" v={dbx ? domain.target : `${domain.name}_graph`} />
            <p className="muted-3" style={{ margin: "10px 0 0", fontSize: 11.5 }}>Read-only facts of the deployment.</p>
          </Card>
        </div>
      </div>
    </>
  );
}
