import { useState } from "react";
import { Button, Card, Pill, Skeleton, Toggle } from "@/components/ui";
import { useApp, useLoad } from "@/state/app";
import { useDomain } from "@/state/domain";

export function Rules() {
  const { api, say } = useApp();
  const { domain, version, editable } = useDomain();
  const rules = useLoad(() => api.rules(domain.name, version!.version), [domain.name, version?.version]);
  const [enabled, setEnabled] = useState<Record<string, boolean>>({});
  return (
    <>
      <div className="page-head">
        <div><h1>Rules</h1><p>SWRL-style rules compiled to SQL. Materialize adds inferred triples; violation flags entities.</p></div>
        <div className="actions"><Button onClick={() => say("OWL RL closure · +23,207 triples")}>Run OWL RL</Button><Button onClick={() => say("2 rules run · +19,204 triples, 0 violations")}>Run rules</Button>{editable && <Button variant="primary" onClick={() => say("New rule")}>New rule</Button>}</div>
      </div>
      <div className="grid" style={{ gap: 12 }}>
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
      </div>
    </>
  );
}
