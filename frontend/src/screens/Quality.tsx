import { Button, Card, Dot, Skeleton } from "@/components/ui";
import { useApp, useLoad } from "@/state/app";
import { useDomain, useGo } from "@/state/domain";

export function Quality() {
  const { api, say } = useApp();
  const { domain, version, editable } = useDomain();
  const go = useGo();
  const rows = useLoad(() => api.constraints(domain.name, version!.version), [domain.name, version?.version]);
  const cols = "1.6fr 1fr 1fr .9fr .8fr 1.4fr";
  return (
    <>
      <div className="page-head">
        <div><h1>Data quality</h1><p>SQL-validated constraints over the built graph. Sample violators link into Explore.</p></div>
        <div className="actions">{editable && <Button onClick={() => say("Derived 3 constraints from ontology restrictions")}>Derive from ontology</Button>}<Button variant="primary" onClick={() => { say("Checks run · 15 violations, 3 warnings"); rows.reload(); }}>Run checks</Button></div>
      </div>
      <Card flush>
        <div className="grid-head" style={{ gridTemplateColumns: cols, padding: "10px 20px" }}><span>Constraint</span><span>Target</span><span>Kind</span><span>Severity</span><span>Violations</span><span>Sample</span></div>
        {rows.loading && <div style={{ padding: 20 }}><Skeleton h={16} /><Skeleton h={16} /></div>}
        {(rows.data ?? []).map(q => (
          <div key={q.name} className="grid-row" style={{ gridTemplateColumns: cols }}>
            <span style={{ fontWeight: 600 }}>{q.name}</span><span>{q.target}</span><span className="mono" style={{ fontSize: 11.5 }}>{q.kind}</span>
            <span className="row"><Dot color={q.severity === "violation" ? "#FF7000" : "#B3B3B7"} />{q.severity}</span>
            <span style={{ fontWeight: 700, color: q.count ? "#B84F00" : "var(--ink)" }}>{q.count}</span>
            <a href="#" className="mono" style={{ fontSize: 11.5 }} onClick={e => { e.preventDefault(); go("explore", q.sampleEntity ? { entity: q.sampleEntity } : {}); }}>{q.sample}</a>
          </div>
        ))}
      </Card>
    </>
  );
}
