// Overview: the domain at a glance and its settings on one page. The Summary tab shows readiness
// above the settings cards (source, connections | domain, MCP policy, lease, review, comments); the
// other tabs of the section bar show one settings card at a time.
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button, Card, CheckDot, Dot } from "@/components/ui";
import { RejectDialog, useLifecycle } from "@/components/lifecycle";
import { useApp, useLoad } from "@/state/app";
import { useDomain, useGo } from "@/state/domain";
import { Settings, type SettingsCard } from "./Settings";
import { STATUS_COLOR } from "@/api";

export function Overview() {
  const { api, can } = useApp();
  const { domain, versions, version } = useDomain();
  const go = useGo();
  const life = useLifecycle();
  const [sp] = useSearchParams();
  const tab = (sp.get("tab") || "all") as SettingsCard;
  const [rejecting, setRejecting] = useState<number | null>(null);
  const inReview = versions.find(v => v.status === "in_review") ?? null;
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
  const next = version?.mappingPct != null && version.mappingPct < 100 ? ["map the unmapped classes", "mapping"] : !built ? ["build the graph", "build"] : ["explore the graph", "explore"];

  const side = (
    <>
      {life.draft && (
        <Card>
          <h2 className="h2" style={{ marginBottom: 10 }}>Lease · v{life.draft.version}</h2>
          {life.draft.lease
            ? <p className="muted" style={{ marginBottom: 12 }}>Held by <strong style={{ color: "var(--ink)", fontWeight: 600 }}>{life.draft.lease.holder}</strong>{life.draft.lease.expired ? ", expired" : `, expires in ${life.draft.lease.expires}`}. Only the holder can edit this draft.</p>
            : <p className="muted" style={{ marginBottom: 12 }}>Nobody holds the lease. Take it to edit the draft; it lasts 15 minutes and renews while you work.</p>}
          {can("builder") && <div className="row">
            {life.draft.lease && life.holdsLease(life.draft) && <Button size="sm" style={{ height: 30 }} onClick={() => life.releaseLease(life.draft!.version)}>Release lease</Button>}
            {(!life.draft.lease || life.draft.lease.expired) && <Button size="sm" variant="primary" style={{ height: 30 }} onClick={() => life.takeLease(life.draft!.version)}>Take lease</Button>}
            {life.draft.lease && !life.holdsLease(life.draft) && can("admin") && <Button size="sm" style={{ height: 30, color: "var(--muted)" }} onClick={() => life.takeLease(life.draft!.version, true)}>Force-take lease</Button>}
          </div>}
        </Card>
      )}
      {rv && inReview && (
        <Card>
          <div className="row between" style={{ alignItems: "baseline" }}><h2 className="h2" style={{ marginBottom: 10 }}>Review · v{inReview.version}</h2><span className="small" style={{ fontWeight: 600, color: "var(--blue-dark)" }}>{rv.approved} of {rv.quorum} approvals</span></div>
          <div className="row" style={{ gap: 4, marginBottom: 12 }}>{Array.from({ length: rv.quorum }, (_, i) => <i key={i} style={{ flex: 1, height: 6, borderRadius: 3, background: i < rv.approved ? "var(--blue)" : "var(--line)" }} />)}</div>
          {rv.rows.map(r => <div key={r.who} className="list-row row between"><span><strong style={{ fontWeight: 600 }}>{r.who}</strong> <span className="muted">{r.note}</span></span><span className="row muted"><Dot color={r.state === "approved" ? STATUS_COLOR.published : r.state === "rejected" ? STATUS_COLOR.in_review : STATUS_COLOR.draft} />{r.state}</span></div>)}
          {rv.rows.length === 0 && <p className="muted small">No reviews yet in this round.</p>}
          {can("reviewer") && <div className="row" style={{ marginTop: 10, flexWrap: "wrap" }}>
            <Button size="sm" variant="primary" style={{ height: 30 }} onClick={() => life.approve(inReview.version)}>Approve</Button>
            <Button size="sm" style={{ height: 30 }} onClick={() => setRejecting(inReview.version)}>Reject with comment</Button>
            {life.quorumMet(inReview) && <Button size="sm" variant="outline" style={{ height: 30 }} onClick={() => life.publish(inReview.version)}>Publish</Button>}
          </div>}
        </Card>
      )}
      <Card>
        <h2 className="h2" style={{ marginBottom: 10 }}>Comments</h2>
        {(comments.data ?? []).map((c, i) => <div key={i} style={{ padding: "10px 0", borderTop: "1px solid var(--line-2)" }}><div className="row between small" style={{ marginBottom: 3 }}><strong style={{ fontWeight: 600 }}>{c.who}</strong><span className="muted-3">{c.when}</span></div><div style={{ color: "var(--ink-2)" }}>{c.text}</div></div>)}
        <form onSubmit={async e => { e.preventDefault(); if (!draft.trim()) return; await api.addComment(domain.name, draft.trim()); setDraft(""); comments.reload(); }}>
          <input id="comment-input" className="input full" style={{ marginTop: 8 }} placeholder="Write a comment…" value={draft} onChange={e => setDraft(e.target.value)} aria-label="Write a comment" />
        </form>
      </Card>
    </>
  );

  return (
    <>
      <div className="page-head" style={{ marginBottom: 20 }}>
        <div><h1>{domain.name} <span className="muted" style={{ fontWeight: 500, fontSize: 20 }}>· {domain.description}</span></h1><p className="mono" style={{ fontSize: 12 }}>{domain.base_iri}</p></div>
        {can("builder") && <div className="actions">
          <Button onClick={() => life.createDraft()}>{life.draft ? "Open current draft" : "Create draft"}</Button>
          {version?.status === "draft" && <Button variant="primary" onClick={() => life.submit(version.version)}>Submit for review</Button>}
        </div>}
      </div>
      {tab === "all" && !version && <Card className="dashed" style={{ marginBottom: 16 }}><div style={{ fontSize: 16, fontWeight: 800, marginBottom: 6 }}>No version yet</div><p className="muted" style={{ marginBottom: 14 }}>Create a draft to start designing the ontology and mapping for {domain.name}.</p>{can("builder") && <Button variant="primary" onClick={() => life.createDraft()}>Create a draft version</Button>}</Card>}
      {tab === "all" && version && (
        <Card style={{ marginBottom: 16 }}>
          <div className="row between" style={{ alignItems: "baseline", marginBottom: 14 }}><h2 className="h2">Readiness · v{version.version}</h2><span className="muted small">Next: <a href="#" style={{ fontWeight: 600 }} onClick={e => { e.preventDefault(); go(next[1]); }}>{next[0]}</a></span></div>
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
      )}
      <Settings embedded only={tab} right={tab === "all" ? side : undefined} />
      <RejectDialog version={rejecting} onClose={() => setRejecting(null)} onReject={life.reject} />
    </>
  );
}
