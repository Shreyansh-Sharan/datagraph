import { useState } from "react";
import { Button, Card, Pill, StatusPill } from "@/components/ui";
import { Icon } from "@/components/icons";
import { DeleteDraftDialog, RejectDialog, downloadJson, useLifecycle } from "@/components/lifecycle";
import { useApp, useLoad } from "@/state/app";
import { useDomain, useGo } from "@/state/domain";
import { STATUS_COLOR, type VersionInfo, type VersionStatus } from "@/api";

const BLUE = "#2249FF", ORANGE = "#FF7000";

export function Versions() {
  const { api, say, can } = useApp();
  const { domain, versions, version: current, setVersion } = useDomain();
  const go = useGo();
  const life = useLifecycle();
  const audit = useLoad(() => api.audit(domain.name), [domain.name, versions]);
  const [cmpOpen, setCmpOpen] = useState(false);
  const [cmpA, setCmpA] = useState(versions[0]?.version ?? 0);
  const [cmpB, setCmpB] = useState(versions[1]?.version ?? versions[0]?.version ?? 0);
  const [rejecting, setRejecting] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  const draftExists = !!life.draft;

  const lifecycle: [VersionStatus, string, string][] = [["draft", "Draft", "edit under a lease"], ["in_review", "In review", `quorum ${domain.quorum}`], ["published", "Published", "one is active"], ["archived", "Archived", "kept for audit"]];
  const rules = [["draft", STATUS_COLOR.draft, "Editable only by the lease holder. Builds run here and never replace the active graph."], ["in review", STATUS_COLOR.in_review, `Read-only. Reviewers approve or reject; publishing needs ${domain.quorum} approval${domain.quorum > 1 ? "s" : ""}.`], ["published", STATUS_COLOR.published, "Immutable. One published version is active and answers MCP and GraphQL; switching active is instant."], ["archived", STATUS_COLOR.archived, "Kept for audit and export. Restore creates a new draft from it."]];

  const vA = versions.find(v => v.version === cmpA) ?? versions[0]; const vB = versions.find(v => v.version === cmpB) ?? versions[1] ?? versions[0];
  const cmpRows = ([["Classes", "classes"], ["Attributes", "attrs"], ["Relationships", "rels"], ["Mapped bindings", "bindings"], ["Rules", "rules"], ["Constraints", "constraints"], ["Triples (last build)", "triples"]] as [string, keyof VersionInfo["stats"]][]).map(([k, f]) => { const a = vA?.stats[f] ?? 0, b = vB?.stats[f] ?? 0, d = a - b; return { k, a: a.toLocaleString(), b: b.toLocaleString(), delta: d === 0 ? "—" : (d > 0 ? "+" : "") + d.toLocaleString(), color: d > 0 ? BLUE : d < 0 ? "#B84F00" : "#97979C" }; });
  const between = versions.filter(v => v.version > (vB?.version ?? 0) && v.version <= (vA?.version ?? 0));
  const cmpChanges = between.flatMap(v => v.changes.map(c => ({ kind: c.sign === "+" ? "added" : c.sign === "-" ? "removed" : "changed", text: `${c.text} (v${v.version})`, plus: c.sign === "+" })));

  const exportBundle = async (v: VersionInfo) => {
    try { downloadJson(`${domain.name}-v${v.version}.bundle.json`, await api.exportBundle(domain.name, v.version)); say(`Exported ${domain.name} v${v.version}`); }
    catch (e) { say(e instanceof Error ? e.message : String(e)); }
  };

  const actionsFor = (v: VersionInfo) => {
    const acts: { label: string; kind: "primary" | "default" | "danger"; go: () => void }[] = [];
    const rv = v.review;
    if (v.status === "draft") {
      if (life.rank >= 1) { acts.push({ label: "Submit for review", kind: "primary", go: () => life.submit(v.version) }); acts.push({ label: "Build", kind: "default", go: () => go("build", { v: v.version }) }); }
      acts.push({ label: "Open", kind: "default", go: () => { setVersion(v.version); go("overview", { v: v.version }); } });
      if (life.rank >= 1) acts.push({ label: "Delete draft", kind: "danger", go: () => setDeleting(v.version) });
    }
    if (v.status === "in_review") {
      if (life.canReview) {
        acts.push({ label: "Approve", kind: "primary", go: () => life.approve(v.version) });
        acts.push({ label: "Reject with comment", kind: "default", go: () => setRejecting(v.version) });
        acts.push({ label: life.quorumMet(v) ? "Publish" : "Publish (quorum not met)", kind: "default", go: () => life.quorumMet(v) ? life.publish(v.version) : say(`Needs ${(rv?.quorum ?? domain.quorum) - (rv?.approved ?? 0)} more approval(s)`) });
      }
      acts.push({ label: "Open", kind: "default", go: () => go("overview", { v: v.version }) });
    }
    if (v.status === "published") {
      if (!v.active && life.canReview) acts.push({ label: "Set active", kind: "primary", go: () => life.setActive(v.version) });
      if (life.rank >= 1) acts.push({ label: "Create draft from this", kind: "default", go: () => life.createDraft(v.version) });
      acts.push({ label: "Explore graph", kind: "default", go: () => go("explore", { v: v.version }) });
      acts.push({ label: "Export bundle", kind: "default", go: () => exportBundle(v) });
      if (life.canReview && !v.active) acts.push({ label: "Archive", kind: "danger", go: () => life.archive(v.version) });
    }
    if (v.status === "archived") {
      if (life.rank >= 1) acts.push({ label: "Restore as draft", kind: "default", go: () => life.createDraft(v.version) });
      acts.push({ label: "Export bundle", kind: "default", go: () => exportBundle(v) });
    }
    return acts;
  };

  const leaseActions = (v: VersionInfo) => {
    if (v.status !== "draft" || life.rank < 1) return null;
    if (!v.lease || v.lease.expired) return <Button size="xs" onClick={() => life.takeLease(v.version)}>Take lease</Button>;
    if (life.holdsLease(v)) return <Button size="xs" onClick={() => life.releaseLease(v.version)}>Release lease</Button>;
    return can("admin") ? <Button size="xs" onClick={() => life.takeLease(v.version, true)}>Force-take lease</Button> : null;
  };

  return (
    <>
      <div className="page-head">
        <div><h1>Versions</h1><p>Every change to {domain.name} lives in a version. Drafts are edited under a lease, reviewed against a quorum of {domain.quorum}, published, and one published version is served as active.</p></div>
        <div className="actions"><Button active={cmpOpen} onClick={() => setCmpOpen(o => !o)}>Compare</Button>{can("builder") && <Button variant="primary" onClick={() => life.createDraft()}>{draftExists ? "Open current draft" : "Create draft"}</Button>}</div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,minmax(0,1fr))", background: "#fff", border: "1px solid var(--line)", borderRadius: 10, overflow: "hidden", marginBottom: 20 }}>
        {lifecycle.map(([id, label, sub], i) => { const n = versions.filter(v => v.status === id).length; const bg = n ? (id === "published" ? BLUE : id === "in_review" ? ORANGE : "#E8E8EA") : "#F4F4F5"; const color = n ? (id === "published" || id === "in_review" ? "#fff" : "#1B1B1C") : "#B3B3B7"; return (
          <div key={id} style={{ padding: "14px 18px", borderRight: "1px solid var(--line-2)", display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ width: 30, height: 30, borderRadius: "50%", background: bg, color, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 800 }}>{n}</span>
            <span><span style={{ display: "block", fontSize: 12.5, fontWeight: 700 }}>{label}</span><span className="muted-2" style={{ display: "block", fontSize: 11 }}>{sub}</span></span>
            {i < 3 && <Icon name="arrow" size={14} stroke="#CFCFD2" style={{ marginLeft: "auto" }} />}
          </div>); })}
      </div>
      {cmpOpen && versions.length > 0 && (
        <Card flush style={{ borderColor: "var(--blue-border)", marginBottom: 20 }}>
          <div className="row" style={{ gap: 12, padding: "14px 20px", borderBottom: "1px solid var(--line)", background: "var(--blue-soft)" }}>
            <strong style={{ fontSize: 14, fontWeight: 800 }}>Compare</strong>
            <select aria-label="Compare version A" className="select" style={{ height: 30 }} value={cmpA} onChange={e => setCmpA(Number(e.target.value))}>{versions.map(v => <option key={v.version} value={v.version}>v{v.version} · {v.status.replace("_", " ")}</option>)}</select>
            <span className="muted small">against</span>
            <select aria-label="Compare version B" className="select" style={{ height: 30 }} value={cmpB} onChange={e => setCmpB(Number(e.target.value))}>{versions.map(v => <option key={v.version} value={v.version}>v{v.version} · {v.status.replace("_", " ")}</option>)}</select>
            <span className="spacer" /><Button size="sm" onClick={() => { downloadJson(`${domain.name}-v${cmpA}-vs-v${cmpB}.diff.json`, { domain: domain.name, a: cmpA, b: cmpB, measures: cmpRows, changes: cmpChanges }); say("Diff exported"); }}>Export diff</Button>
          </div>
          <div className="grid-head" style={{ gridTemplateColumns: "1.4fr 1fr 1fr 1fr" }}><span>Measure</span><span>v{cmpA}</span><span>v{cmpB}</span><span>Delta</span></div>
          {cmpRows.map(r => <div key={r.k} className="grid-row" style={{ gridTemplateColumns: "1.4fr 1fr 1fr 1fr", padding: "9px 20px" }}><span style={{ fontWeight: 600 }}>{r.k}</span><span className="mono small">{r.a}</span><span className="mono small">{r.b}</span><span className="mono small" style={{ fontWeight: 600, color: r.color }}>{r.delta}</span></div>)}
          <div style={{ padding: "12px 20px 16px", borderTop: "1px solid var(--line)" }}>
            <div className="label-caps" style={{ marginBottom: 6 }}>Changes in v{cmpA} not in v{cmpB}</div>
            {cmpChanges.map((c, i) => <div key={i} className="row" style={{ gap: 10, padding: "5px 0", fontSize: 12.5 }}><span className="pill mini" style={{ height: 18, fontSize: 10, background: c.plus ? "var(--blue-soft)" : "#fff", color: c.plus ? "var(--blue-dark)" : "var(--orange-text)", border: `1px solid ${c.plus ? "var(--blue-border)" : "var(--orange)"}` }}>{c.kind}</span><span>{c.text}</span></div>)}
            {cmpChanges.length === 0 && <p className="muted small">No recorded changes between these versions.</p>}
          </div>
        </Card>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.5fr) minmax(0,1fr)", gap: 20, alignItems: "start" }}>
        <div style={{ position: "relative", paddingLeft: 28 }}>
          <i style={{ position: "absolute", left: 9, top: 12, bottom: 12, width: 2, background: "var(--line)" }} />
          {versions.map((v, i) => {
            const prev = versions[i + 1]; const rv = v.review; const st = v.stats; const dot = STATUS_COLOR[v.status];
            const flags = [[`${st.classes} classes`, st.classes > 0], [`mapping ${v.mappingPct ?? "—"}%`, v.mappingPct === 100], [`${st.rules} rules`, st.rules > 0], [`${st.constraints} constraints`, st.constraints > 0], [v.lastBuild.replace(" · ", " "), v.lastBuild.startsWith("succeeded")]] as [string, boolean][];
            return (
              <div key={v.version} style={{ position: "relative", marginBottom: 14 }}>
                <i style={{ position: "absolute", left: -24, top: 18, width: 12, height: 12, borderRadius: "50%", background: dot, border: "2px solid #fff", boxShadow: `0 0 0 2px ${dot}` }} />
                <Card style={{ padding: "16px 20px", borderColor: v.version === current?.version ? BLUE : undefined }}>
                  <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
                    <strong style={{ fontSize: 17, fontWeight: 800 }}>v{v.version}</strong><StatusPill status={v.status} />
                    {v.active && <Pill tone="mini" style={{ fontSize: 10.5, color: "var(--blue-dark)", background: "var(--blue-soft)", padding: "2px 8px", height: "auto" }}>ACTIVE · served to MCP</Pill>}
                    {v.version === current?.version && <Pill tone="outline" style={{ fontSize: 10.5, height: "auto", padding: "1px 8px" }}>viewing</Pill>}
                    <span className="muted-2 small" style={{ marginLeft: "auto" }}>{v.created}{v.by ? ` · ${v.by}` : ""}</span>
                  </div>
                  <div style={{ marginTop: 10, display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {flags.map(([label, ok]) => <Pill key={label} size="lg" dot={ok ? BLUE : ORANGE} style={{ border: `1px solid ${ok ? "var(--blue-border)" : "var(--line)"}`, background: ok ? "var(--blue-soft)" : "#fff", color: ok ? "var(--blue-dark)" : "var(--ink-2)" }}>{label}</Pill>)}
                  </div>
                  {v.changes.length > 0 && <div style={{ marginTop: 12, padding: "10px 12px", borderRadius: 8, background: "var(--surface-2)", border: "1px solid var(--line-2)" }}>
                    <div className="label-caps" style={{ fontSize: 10.5, color: "var(--muted-2)", marginBottom: 4 }}>Changes since v{prev ? prev.version : "—"}</div>
                    {v.changes.map((c, k) => <div key={k} className="row" style={{ padding: "3px 0", fontSize: 12.5, color: "var(--ink-2)" }}><span className="mono" style={{ width: 16, fontWeight: 600, color: c.sign === "+" ? BLUE : c.sign === "-" ? "#B84F00" : "#7A7A80" }}>{c.sign}</span>{c.text}</div>)}
                  </div>}
                  {rv && <div className="row" style={{ marginTop: 12, gap: 10, fontSize: 12, flexWrap: "wrap" }}><span className="muted">Review{rv.round && rv.round > 1 ? ` · round ${rv.round}` : ""}</span><div className="row" style={{ gap: 3, width: 120 }}>{Array.from({ length: rv.quorum }, (_, k) => <i key={k} style={{ flex: 1, height: 6, borderRadius: 3, background: k < rv.approved ? BLUE : "var(--line)" }} />)}</div><span style={{ fontWeight: 600, color: "var(--blue-dark)" }}>{rv.approved} of {rv.quorum}</span><span className="muted-2">{rv.rows.map(r => `${r.who} ${r.state === "approved" ? "✓" : r.state === "rejected" ? "✗" : "·"}`).join("  ")}</span></div>}
                  {(v.lease || v.status === "draft") && <div className="row muted small" style={{ marginTop: 10, gap: 10 }}>
                    <span>{v.lease ? <>Lease held by <strong style={{ color: "var(--ink)", fontWeight: 600 }}>{v.lease.holder}</strong>{v.lease.expired ? ", expired" : `, expires in ${v.lease.expires}`}</> : "No lease · anyone with the builder role can take it"}</span>
                    {leaseActions(v)}
                  </div>}
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 14 }}>
                    {actionsFor(v).map(a => <Button key={a.label} size="sm" variant={a.kind === "primary" ? "primary" : a.kind === "danger" ? "danger-text" : "default"} onClick={a.go}>{a.label}</Button>)}
                  </div>
                </Card>
              </div>
            );
          })}
          {versions.length === 0 && <Card className="dashed"><div style={{ fontSize: 16, fontWeight: 800, marginBottom: 6 }}>No version yet</div><p className="muted" style={{ marginBottom: 14 }}>Create the first draft for {domain.name}.</p><Button variant="primary" onClick={() => life.createDraft()}>Create a draft version</Button></Card>}
        </div>
        <div className="grid">
          <Card><h2 className="h2" style={{ marginBottom: 6 }}>Lifecycle rules</h2>{rules.map(([state, dot, text]) => <div key={state} style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 10, padding: "8px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5, color: "var(--ink-2)" }}><Pill dot={dot}>{state}</Pill><span>{text}</span></div>)}</Card>
          <Card>
            <div className="row between" style={{ alignItems: "baseline", marginBottom: 6 }}><h2 className="h2">Audit log</h2><a href="#" className="small" style={{ fontWeight: 600 }} onClick={e => { e.preventDefault(); downloadJson(`${domain.name}-audit.json`, audit.data ?? []); say("Audit log exported"); }}>Export</a></div>
            {(audit.data ?? []).map((a, i) => <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 10, padding: "8px 0", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}><span><strong style={{ fontWeight: 600 }}>{a.who}</strong> <span style={{ color: "var(--ink-2)" }}>{a.what}</span> <span className="mono" style={{ fontSize: 11, color: "var(--muted-2)" }}>v{a.version}</span></span><span className="muted-3" style={{ fontSize: 11.5, whiteSpace: "nowrap" }}>{a.when}</span></div>)}
            {audit.data && audit.data.length === 0 && <p className="muted small">Nothing recorded yet.</p>}
          </Card>
        </div>
      </div>
      <RejectDialog version={rejecting} onClose={() => setRejecting(null)} onReject={life.reject} />
      <DeleteDraftDialog version={deleting} onClose={() => setDeleting(null)} onDelete={life.deleteDraft} />
    </>
  );
}
