import { useState } from "react";
import { Button, Card, CheckDot, Dot, KV, Pill, StatusPill } from "@/components/ui";
import { useApp, useLoad } from "@/state/app";
import { useDomain, useGo } from "@/state/domain";
import { STATUS_COLOR } from "@/api";

export function Overview() {
  const { api, config, say, can } = useApp();
  const { domain, versions, version, setVersion, patch } = useDomain();
  const go = useGo();
  const dbx = config.sourceKind === "databricks";
  const comments = useLoad(() => api.comments(domain.name), [domain.name]);
  const builds = useLoad(() => version ? api.builds(domain.name, version.version) : Promise.resolve([]), [domain.name, version?.version]);
  const [draft, setDraft] = useState("");
  const lastBuild = builds.data?.[0];
  const built = lastBuild?.status === "succeeded";
  const rv = domain.review;

  const readiness = [
    { label: "Ontology", value: `${version?.stats.classes ?? 0} classes`, sub: "0 check errors", ok: true, screen: "ontology" },
    { label: "Mapping", value: version?.mappingPct != null ? `${version.mappingPct}%` : "—", sub: version?.mappingPct === 100 ? "all classes mapped" : "2 classes unmapped", ok: version?.mappingPct === 100, screen: "mapping" },
    { label: "Build", value: lastBuild ? lastBuild.status[0].toUpperCase() + lastBuild.status.slice(1) : "never", sub: built ? `${lastBuild.triples} triples` : "—", ok: !!built, screen: "build" },
    { label: "Drift", value: "1 issue", sub: "fct_sales.channel_id missing", ok: false, screen: "metadata" },
  ];
  const config_ = [["Base IRI", domain.base_iri], ["Review quorum", String(domain.quorum)], ["Source", dbx ? `databricks · ${domain.catalog}` : `postgres · ${domain.catalog}_${domain.schema}`], ["Default schema", domain.schema], ["Materialization", domain.materialization], ["MCP", domain.mcpExposed ? `exposed · ${domain.disabledTools.length} tools off` : "hidden"]];

  return (
    <>
      <div className="page-head" style={{ marginBottom: 24 }}>
        <div><h1>{domain.name} <span className="muted" style={{ fontWeight: 500, fontSize: 20 }}>· {domain.description}</span></h1><p className="mono" style={{ fontSize: 12 }}>{domain.base_iri}</p></div>
        {can("builder") && <div className="actions">
          <Button onClick={async () => { patch(await api.createDraft(domain.name)); say("Draft created"); }}>Create draft</Button>
          {version?.status === "draft" && <Button variant="primary" onClick={async () => { patch(await api.transition(domain.name, version.version, "in_review")); say(`v${version.version} submitted for review`); }}>Submit for review</Button>}
        </div>}
      </div>
      <div className="grid wide-narrow">
        <div className="grid">
          {!version && <Card className="dashed"><div style={{ fontSize: 16, fontWeight: 800, marginBottom: 6 }}>No version yet</div><p className="muted" style={{ marginBottom: 14 }}>Create a draft to start designing the ontology and mapping for {domain.name}.</p>{can("builder") && <Button variant="primary" onClick={async () => { patch(await api.createDraft(domain.name)); say("Draft v1 created"); }}>Create a draft version</Button>}</Card>}
          {version && (
            <>
              <Card>
                <div className="row between" style={{ alignItems: "baseline", marginBottom: 14 }}><h2 className="h2">Readiness · v{version.version}</h2><span className="muted small">Next: <a href="#" style={{ fontWeight: 600 }} onClick={e => { e.preventDefault(); go("mapping", { cls: "Channel" }); }}>map Channel and Shipment</a></span></div>
                <div className="grid cols-4">
                  {readiness.map(r => (
                    <a key={r.label} href="#" onClick={e => { e.preventDefault(); go(r.screen); }} style={{ display: "block", padding: 14, borderRadius: 8, border: "1px solid var(--line)", color: "var(--ink)" }}>
                      <div className="row" style={{ fontSize: 12, color: "var(--muted)", fontWeight: 600 }}><CheckDot ok={r.ok} />{r.label}</div>
                      <div style={{ marginTop: 8, fontSize: 22, fontWeight: 800, letterSpacing: "-.02em" }}>{r.value}</div>
                      <div className="muted-2 xs">{r.sub}</div>
                    </a>
                  ))}
                </div>
              </Card>
              <Card flush>
                <div className="card-head" style={{ alignItems: "center" }}><h2 className="h2">Versions</h2><a href="#" className="small" style={{ fontWeight: 600 }} onClick={e => { e.preventDefault(); go("versions"); }}>Manage versions →</a></div>
                <div className="grid-head" style={{ gridTemplateColumns: ".6fr 1fr 1.6fr 1fr 1fr" }}><span>Version</span><span>Status</span><span>Content</span><span>Last build</span><span /></div>
                {versions.map(v => (
                  <div key={v.version} className="grid-row" style={{ gridTemplateColumns: ".6fr 1fr 1.6fr 1fr 1fr", padding: "12px 20px", borderTopColor: "var(--line)" }}>
                    <span style={{ fontWeight: 700 }}>v{v.version} {v.active && <Pill tone="mini" style={{ marginLeft: 6, color: "var(--blue-dark)", background: "var(--blue-soft)" }}>ACTIVE</Pill>}</span>
                    <StatusPill status={v.status} />
                    <span className="muted small">{v.content}</span>
                    <span className="muted small">{v.lastBuild}</span>
                    <span className="row" style={{ justifyContent: "flex-end", gap: 6 }}>
                      <Button size="sm" style={{ height: 26 }} onClick={() => setVersion(v.version)}>Open</Button>
                      {!v.active && v.status === "published" && can("reviewer") && <Button size="sm" variant="outline" style={{ height: 26 }} onClick={async () => { patch(await api.transition(domain.name, v.version, "active")); say(`v${v.version} is now served to MCP and GraphQL`); }}>Set active</Button>}
                    </span>
                  </div>
                ))}
              </Card>
            </>
          )}
        </div>
        <div className="grid">
          <Card>
            <div className="row between" style={{ marginBottom: 6 }}><h2 className="h2">Configuration</h2><a href="#" className="small" style={{ fontWeight: 600 }} onClick={e => { e.preventDefault(); go("settings"); }}>Edit in Settings</a></div>
            {config_.map(([k, v]) => <KV key={k} k={k} v={v} />)}
          </Card>
          {domain.lease && (
            <Card>
              <h2 className="h2" style={{ marginBottom: 10 }}>Lease</h2>
              <p className="muted" style={{ marginBottom: 12 }}>Held by <strong style={{ color: "var(--ink)", fontWeight: 600 }}>{domain.lease.holder}</strong>, expires in {domain.lease.expires}. Only the holder can edit this draft.</p>
              <div className="row"><Button size="sm" style={{ height: 30 }} onClick={() => say("Lease released")}>Release</Button>{can("admin") && <Button size="sm" style={{ height: 30, color: "var(--muted)" }} onClick={() => say("Lease taken")}>Force-take</Button>}</div>
            </Card>
          )}
          {rv && (
            <Card>
              <div className="row between" style={{ alignItems: "baseline" }}><h2 className="h2" style={{ marginBottom: 10 }}>Review</h2><span className="small" style={{ fontWeight: 600, color: "var(--blue-dark)" }}>{rv.approved} of {rv.quorum} approvals</span></div>
              <div className="row" style={{ gap: 4, marginBottom: 12 }}>{Array.from({ length: rv.quorum }, (_, i) => <i key={i} style={{ flex: 1, height: 6, borderRadius: 3, background: i < rv.approved ? "var(--blue)" : "var(--line)" }} />)}</div>
              {rv.rows.map(r => <div key={r.who} className="list-row row between"><span><strong style={{ fontWeight: 600 }}>{r.who}</strong> <span className="muted">{r.note}</span></span><span className="row muted"><Dot color={r.state === "approved" ? STATUS_COLOR.published : STATUS_COLOR.draft} />{r.state}</span></div>)}
              {can("reviewer") && <div className="row" style={{ marginTop: 10 }}><Button size="sm" variant="primary" style={{ height: 30 }} onClick={() => say(`Approved · ${rv.approved + 1} of ${rv.quorum}`)}>Approve</Button><Button size="sm" style={{ height: 30 }} onClick={() => say("Sent back to draft with your comment")}>Reject with comment</Button></div>}
            </Card>
          )}
          <Card>
            <h2 className="h2" style={{ marginBottom: 10 }}>Comments</h2>
            {(comments.data ?? []).map((c, i) => <div key={i} style={{ padding: "10px 0", borderTop: "1px solid var(--line-2)" }}><div className="row between small" style={{ marginBottom: 3 }}><strong style={{ fontWeight: 600 }}>{c.who}</strong><span className="muted-3">{c.when}</span></div><div style={{ color: "var(--ink-2)" }}>{c.text}</div></div>)}
            <form onSubmit={async e => { e.preventDefault(); if (!draft.trim()) return; await api.addComment(domain.name, draft.trim()); setDraft(""); comments.reload(); }}>
              <input id="comment-input" className="input full" style={{ marginTop: 8 }} placeholder="Write a comment…" value={draft} onChange={e => setDraft(e.target.value)} aria-label="Write a comment" />
            </form>
          </Card>
        </div>
      </div>
    </>
  );
}
