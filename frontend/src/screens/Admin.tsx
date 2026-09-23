import { useState } from "react";
import { Button, Card, Dialog, EmptyState, Label, Skeleton } from "@/components/ui";
import { useApp, useLoad } from "@/state/app";
import type { Role } from "@/api";

export function Admin() {
  const { api, say, can } = useApp();
  const [newKey, setNewKey] = useState<{ name: string; principal: string; role: Role } | null>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const act = async (what: string, run: () => Promise<unknown>, after?: () => void) => {
    try { await run(); after?.(); say(what); }
    catch (e) { say(e instanceof Error ? e.message : String(e)); }
  };
  const principals = useLoad(() => api.principals(), []);
  const keys = useLoad(() => api.apiKeys(), []);
  const locks = useLoad(() => api.locks(), []);
  if (!can("admin")) return <EmptyState icon="shield" title="Admin only" text="Principals, API keys and locks need the admin role." />;
  return (
    <>
      <div className="page-head"><div><h1>Admin</h1><p>Principals and roles, API keys, locks.</p></div><div className="actions"><Button variant="primary" onClick={() => { setSecret(null); setNewKey({ name: "", principal: "", role: "viewer" }); }}>New API key</Button></div></div>
      <div className="grid two">
        <Card flush>
          <div className="card-head"><h2 className="h2">Principals</h2></div>
          <div className="grid-head" style={{ gridTemplateColumns: "1fr 1fr 1fr" }}><span>Name</span><span>Role</span><span>Last seen</span></div>
          {principals.loading && <div style={{ padding: 20 }}><Skeleton h={16} /></div>}
          {(principals.data ?? []).map(p => <div key={p.name} className="grid-row" style={{ gridTemplateColumns: "1fr 1fr 1fr", padding: "10px 20px" }}><span style={{ fontWeight: 600 }}>{p.name}</span><select aria-label={`Role of ${p.name}`} className="select" style={{ height: 28, width: 120 }} defaultValue={p.role} onChange={e => void act(`${p.name} is now ${e.target.value}`, () => api.setPrincipalRole(p.name, e.target.value as Role), principals.reload)}>{["viewer", "builder", "reviewer", "admin"].map(r => <option key={r}>{r}</option>)}</select><span className="muted">{p.seen}</span></div>)}
        </Card>
        <div className="grid">
          <Card flush>
            <div className="card-head"><h2 className="h2">API keys</h2></div>
            {(keys.data ?? []).map(k => <div key={k.name} className="row between" style={{ padding: "10px 20px", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}><span><div style={{ fontWeight: 600 }}>{k.name}</div><div className="mono muted-2" style={{ fontSize: 11.5 }}>{k.prefix} · {k.role}</div></span><Button size="xs" variant="danger" style={{ height: 26 }} aria-label={`Revoke ${k.name}`} onClick={() => void act(`${k.name} revoked`, () => api.revokeApiKey(k.name), keys.reload)}>Revoke</Button></div>)}
          </Card>
          <Card flush>
            <div className="card-head"><h2 className="h2">Locks</h2></div>
            {(locks.data ?? []).map(l => <div key={l.what} className="row between" style={{ padding: "10px 20px", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}><span><strong style={{ fontWeight: 600 }}>{l.what}</strong> <span className="muted">held by {l.who}, expires in {l.exp}</span></span><Button size="xs" style={{ height: 26 }} disabled={!l.id} onClick={() => void act(`Released the lease on ${l.what}`, () => api.forceRelease(l.id!), locks.reload)}>Force release</Button></div>)}
          </Card>
        </div>
      </div>
      <Dialog title={secret ? "API key created" : "New API key"} open={!!newKey} onClose={() => { setNewKey(null); setSecret(null); }} width={460}
              footer={secret ? <Button variant="primary" onClick={() => { setNewKey(null); setSecret(null); }}>Done</Button>
                             : <><Button onClick={() => setNewKey(null)}>Cancel</Button>
                                 <Button variant="primary" disabled={!newKey?.name.trim() || !newKey?.principal.trim()}
                                         onClick={() => void act("API key created", async () => { const r = await api.createApiKey(newKey!.name.trim(), newKey!.principal.trim(), newKey!.role); setSecret(r.secret); }, keys.reload)}>Create key</Button></>}>
        {secret
          ? <div style={{ display: "grid", gap: 8 }}><p className="muted small">Copy it now. It is shown once and cannot be read again.</p><code className="mono" style={{ padding: "10px 12px", background: "var(--surface-3)", borderRadius: 8, wordBreak: "break-all" }}>{secret}</code></div>
          : <div style={{ display: "grid", gap: 12 }}>
              <div><Label>Name</Label><input className="input full" aria-label="Key name" placeholder="What uses this key" value={newKey?.name ?? ""} onChange={e => setNewKey(k => k && { ...k, name: e.target.value })} /></div>
              <div><Label>Acts as</Label><input className="input full mono" aria-label="Principal" placeholder="svc-insight-portal" value={newKey?.principal ?? ""} onChange={e => setNewKey(k => k && { ...k, principal: e.target.value })} /></div>
              <div><Label>Role</Label><select className="select full" aria-label="Key role" value={newKey?.role ?? "viewer"} onChange={e => setNewKey(k => k && { ...k, role: e.target.value as Role })}>{["viewer", "builder", "reviewer", "admin"].map(r => <option key={r}>{r}</option>)}</select></div>
            </div>}
      </Dialog>
    </>
  );
}
