// The version mechanism as the screens use it: one hook with every lifecycle action (each one
// calls the API, mirrors the result into the domain state and tells the user what happened,
// or why it did not), plus the two confirmations that need a dialog.
import { useState } from "react";
import { Button, Dialog, Label } from "@/components/ui";
import { useApp } from "@/state/app";
import { useDomain } from "@/state/domain";
import type { DomainSummary, VersionInfo, VersionStatus } from "@/api";

type Msg = string | ((d: DomainSummary) => string);

export function useLifecycle() {
  const { api, say, me, rank } = useApp();
  const { domain, versions, patch, setVersion } = useDomain();
  const name = domain.name;

  const run = async (fn: () => Promise<DomainSummary>, msg: Msg): Promise<boolean> => {
    try { const d = await fn(); patch(d); say(typeof msg === "function" ? msg(d) : msg); return true; }
    catch (e) { say(e instanceof Error ? e.message : String(e)); return false; }
  };
  const find = (d: DomainSummary, v: number) => d.versions.find(x => x.version === v);
  const draft = versions.find(v => v.status === "draft") ?? null;

  return {
    me, rank, draft,
    /** Who may do what to this version, mirroring the backend's role checks. */
    canEdit: (v: VersionInfo) => v.status === "draft" && rank >= 1 && (!v.lease || v.lease.holder === me.name || v.lease.expired === true),
    canReview: rank >= 2,
    holdsLease: (v: VersionInfo) => !!v.lease && v.lease.holder === me.name,
    quorumMet: (v: VersionInfo) => !!v.review && v.review.approved >= v.review.quorum,

    submit: (v: number) => run(() => api.transition(name, v, "in_review"), `v${v} submitted for review`),
    approve: (v: number) => run(() => api.review(name, v, true), d => { const rv = find(d, v)?.review; return `Approved v${v} · ${rv?.approved ?? 1} of ${rv?.quorum ?? domain.quorum}`; }),
    reject: (v: number, comment: string) => run(() => api.review(name, v, false, comment), `v${v} sent back to draft`),
    publish: (v: number) => run(() => api.transition(name, v, "published"), `v${v} published`),
    setActive: (v: number) => run(() => api.transition(name, v, "active"), `v${v} is now served to MCP and GraphQL`),
    archive: (v: number) => run(() => api.transition(name, v, "archived"), `v${v} archived`),
    transition: (v: number, to: VersionStatus | "active", msg: string) => run(() => api.transition(name, v, to), msg),
    deleteDraft: (v: number) => run(() => api.deleteDraft(name, v), `Draft v${v} deleted`),
    takeLease: (v: number, force = false) => run(() => api.takeLease(name, v, force), force ? `Lease on v${v} taken over` : `You hold the lease on v${v} for 15 min`),
    releaseLease: (v: number) => run(() => api.releaseLease(name, v), `Lease on v${v} released`),
    createDraft: async (from?: number) => {
      if (draft) { say(`Draft v${draft.version} already exists · opening it`); setVersion(draft.version); return true; }
      return run(() => api.createDraft(name, from), d => `Draft v${d.versions[0]?.version ?? 1} created${from ? ` from v${from}` : ""}`);
    },
  };
}

/** Rejecting needs a reason: it is recorded as the review and as a comment, and the version reopens as a draft. */
export function RejectDialog({ version, onClose, onReject }: { version: number | null; onClose: () => void; onReject: (v: number, comment: string) => Promise<boolean> }) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const close = () => { setComment(""); onClose(); };
  const submit = async () => { if (version == null) return; setBusy(true); const ok = await onReject(version, comment.trim()); setBusy(false); if (ok) close(); };
  return (
    <Dialog title={`Reject v${version ?? ""}`} open={version != null} onClose={close}
      footer={<><Button onClick={close}>Cancel</Button><Button variant="primary" disabled={!comment.trim() || busy} onClick={submit}>Reject and reopen draft</Button></>}>
      <p className="muted" style={{ marginBottom: 12 }}>Your comment goes to the author and the version returns to draft. Approvals from this review round are discarded.</p>
      <Label>Comment</Label>
      <textarea id="reject-comment" className="textarea full" rows={4} aria-label="Comment" placeholder="What needs to change before this can be published?" value={comment} onChange={e => setComment(e.target.value)} style={{ width: "100%" }} />
    </Dialog>
  );
}

/** Deleting a draft is the one destructive version action, so the number has to be typed. */
export function DeleteDraftDialog({ version, onClose, onDelete }: { version: number | null; onClose: () => void; onDelete: (v: number) => Promise<boolean> }) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const close = () => { setTyped(""); onClose(); };
  const confirm = async () => { if (version == null) return; setBusy(true); const ok = await onDelete(version); setBusy(false); if (ok) close(); };
  const match = version != null && typed.trim() === String(version);
  return (
    <Dialog title={`Delete draft v${version ?? ""}`} open={version != null} onClose={close}
      footer={<><Button onClick={close}>Cancel</Button><Button variant="danger" disabled={!match || busy} onClick={confirm}>Delete draft</Button></>}>
      <p className="muted" style={{ marginBottom: 12 }}>The ontology, mapping, rules, builds and comments of this draft are removed. Published versions are never affected.</p>
      <Label>Type {version} to confirm</Label>
      <input id="delete-confirm" className="input mono" aria-label={`Type ${version} to confirm`} value={typed} onChange={e => setTyped(e.target.value)} style={{ width: 120 }} />
    </Dialog>
  );
}

/** Downloads any JSON-serialisable value as a file, for the export links. */
export function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
