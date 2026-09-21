import { Button, Card, Skeleton } from "@/components/ui";
import { useApp, useLoad } from "@/state/app";
import { useDomain, useGo } from "@/state/domain";

const TONE = { blue: "#2249FF", ink: "var(--ink)", warn: "#B84F00" };

export function Analytics() {
  const { api, say } = useApp();
  const { domain, version } = useDomain();
  const go = useGo();
  const a = useLoad(() => api.analytics(domain.name), [domain.name]);
  const max = Math.max(1, ...(a.data?.perClass.map(c => c.n) ?? [1]));
  return (
    <>
      <div className="page-head">
        <div><h1>Analytics</h1><p>Graph health for v{version?.version}, plus centrality and community runs.</p></div>
        <div className="actions"><Button onClick={() => say("Centralities · top 50 in 18 s")}>Run centralities</Button><Button variant="primary" onClick={() => say("Louvain · 14 communities")}>Detect communities</Button></div>
      </div>
      {a.loading && <Skeleton h={200} />}
      {a.data && (
        <>
          <div className="grid cols-4" style={{ marginBottom: 20 }}>
            {a.data.health.map(h => <Card key={h.label} style={{ padding: "16px 18px" }}><div className="label-caps">{h.label}</div><div style={{ fontSize: 30, fontWeight: 800, letterSpacing: "-.02em", marginTop: 4, color: TONE[h.tone] }}>{h.value}</div><div className="muted-2" style={{ fontSize: 11.5 }}>{h.sub}</div></Card>)}
          </div>
          <div className="grid two">
            <Card>
              <h2 className="h2" style={{ marginBottom: 12 }}>Entities per class</h2>
              {a.data.perClass.map(c => <div key={c.label} style={{ display: "grid", gridTemplateColumns: "110px 1fr 70px", alignItems: "center", gap: 12, padding: "5px 0", fontSize: 12.5 }}><span style={{ fontWeight: 600 }}>{c.label}</span><div style={{ height: 10, borderRadius: 5, background: "var(--surface-3)", overflow: "hidden" }}><div style={{ height: "100%", width: `${Math.round(c.n / max * 100)}%`, background: c.color, borderRadius: 5 }} /></div><span className="mono small" style={{ textAlign: "right" }}>{c.n.toLocaleString()}</span></div>)}
            </Card>
            <Card flush>
              <div className="card-head"><h2 className="h2">Runs</h2><a href="#" className="small" style={{ fontWeight: 600 }} onClick={e => { e.preventDefault(); say("Interpreting the last run with AI…"); }}>Interpret with AI</a></div>
              <div className="grid-head" style={{ gridTemplateColumns: "1.3fr 1fr 1fr 1fr" }}><span>Kind</span><span>Params</span><span>Result</span><span>When</span></div>
              {a.data.runs.map(r => <div key={r.kind} className="grid-row" style={{ gridTemplateColumns: "1.3fr 1fr 1fr 1fr", padding: "10px 20px" }}><span style={{ fontWeight: 600 }}>{r.kind}</span><span className="mono muted" style={{ fontSize: 11.5 }}>{r.params}</span><span>{r.result}</span><span className="muted">{r.when}</span></div>)}
              <div style={{ padding: "14px 20px 16px", borderTop: "1px solid var(--line)" }}>
                <h3 className="label-caps" style={{ marginBottom: 6, fontSize: 12 }}>Top betweenness</h3>
                {a.data.top.map(n => <a key={n.label} href="#" className="row between" style={{ padding: "6px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5, color: "var(--ink)" }} onClick={e => { e.preventDefault(); go("explore", { entity: n.entity }); }}><span>{n.label} <span className="muted-2" style={{ fontSize: 11.5 }}>{n.type}</span></span><span className="mono small">{n.score}</span></a>)}
              </div>
            </Card>
          </div>
        </>
      )}
    </>
  );
}
