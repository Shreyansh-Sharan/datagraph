import { useState } from "react";
import { Button, Card, Dot, KV, Label, Spinner, Toggle } from "@/components/ui";
import { useApp } from "@/state/app";
import { useDomain } from "@/state/domain";
import type { ConnResult } from "@/api";

export function Settings() {
  const { api, config, say } = useApp();
  const { domain, patch } = useDomain();
  const dbx = config.sourceKind === "databricks";
  const [testing, setTesting] = useState(false);
  const [conn, setConn] = useState<ConnResult | null>(null);
  const [mcp, setMcp] = useState(domain.mcpExposed);
  const facts: [string, string][] = dbx
    ? [["Kind", "databricks"], ["Catalog", config.catalog ?? "—"], ["Domain catalog · schema", `${domain.catalog} · ${domain.schema}`], ["Auth mode", `${config.authMode} · ${config.authHeader}`], ["Materialization", domain.materialization]]
    : [["Kind", "postgres"], ["Domain schema", `${domain.catalog}_${domain.schema}`], ["Auth mode", `${config.authMode} · ${config.authHeader}`], ["Materialization", "view"], ["IRI helper", "ontoforge_iri_encode()"]];
  const test = async () => { if (testing) return; setTesting(true); setConn(null); try { setConn(await api.testConnection()); } finally { setTesting(false); } };
  return (
    <>
      <div className="page-head"><div><h1>Settings</h1><p>Domain description, what MCP exposes, attachments, and the source adapter this deployment runs.</p></div></div>
      <div className="grid two">
        <Card>
          <div className="row between" style={{ marginBottom: 10 }}><h2 className="h2">Source</h2><Button size="sm" variant="outline" style={{ height: 30 }} onClick={test}>{testing && <Spinner blue />}Test connection</Button></div>
          {facts.map(([k, v]) => <KV key={k} k={k} v={v} />)}
          {conn && (
            <div className="notice" style={{ borderColor: conn.ok ? "var(--blue-border)" : "var(--orange)", background: conn.ok ? "var(--blue-soft)" : "#fff" }}>
              <div className="row" style={{ fontWeight: 700, color: conn.ok ? "var(--blue)" : "var(--orange)" }}><Dot color={conn.ok ? "var(--blue)" : "var(--orange)"} size={8} />{conn.title}</div>
              <div className="mono" style={{ marginTop: 4, color: "var(--ink-2)", fontSize: 11.5, whiteSpace: "pre-wrap" }}>{conn.detail}</div>
              {conn.action && <div style={{ marginTop: 6 }}>{conn.action}</div>}
            </div>
          )}
          <p className="muted-3" style={{ margin: "12px 0 0", fontSize: 11.5 }}>Secrets stay in the environment and are never shown here.</p>
        </Card>
        <div className="grid">
          <Card>
            <h2 className="h2" style={{ marginBottom: 10 }}>MCP policy</h2>
            <div className="row between" style={{ padding: "8px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}><span><strong style={{ fontWeight: 600 }}>Expose this domain to agents</strong><div className="muted small">Active version answers over MCP and GraphQL</div></span><Toggle on={mcp} label="Expose this domain to agents" onChange={async v => { setMcp(v); await api.setMcp(domain.name, v); patch({ ...domain, mcpExposed: v }); say(v ? "Domain exposed to agents" : "Domain hidden from agents"); }} /></div>
            <div className="muted small" style={{ paddingTop: 8, borderTop: "1px solid var(--line-2)" }}>Disabled tools</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>{domain.disabledTools.map(t => <span key={t} className="pill mono" style={{ height: 24, padding: "0 10px", border: "1px solid var(--grey-2)", background: "#fff", fontSize: 12 }}>{t}</span>)}<Button dashed onClick={() => say("Pick a tool to disable")}>+ Disable a tool</Button></div>
          </Card>
          <Card>
            <h2 className="h2" style={{ marginBottom: 10 }}>Domain</h2>
            <Label>Description</Label><input id="s-desc" className="input full" defaultValue={domain.description} style={{ marginBottom: 12 }} />
            <Label>Review quorum</Label><input id="s-quorum" className="input" type="number" min={1} defaultValue={domain.quorum} style={{ width: 100, marginBottom: 12 }} />
            <Label>Base IRI</Label><input id="s-iri" className="input mono full" defaultValue={domain.base_iri} />
            <div className="row" style={{ marginTop: 14, justifyContent: "flex-end" }}><Button variant="primary" size="sm" onClick={() => say("Domain settings saved")}>Save changes</Button></div>
          </Card>
        </div>
      </div>
    </>
  );
}
