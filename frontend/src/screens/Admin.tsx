import { Button, Card, EmptyState, Skeleton } from "@/components/ui";
import { useApp, useLoad } from "@/state/app";

export function Admin() {
  const { api, say, can } = useApp();
  const principals = useLoad(() => api.principals(), []);
  const keys = useLoad(() => api.apiKeys(), []);
  const locks = useLoad(() => api.locks(), []);
  if (!can("admin")) return <EmptyState icon="shield" title="Admin only" text="Principals, API keys and locks need the admin role." />;
  return (
    <>
      <div className="page-head"><div><h1>Admin</h1><p>Principals and roles, API keys, locks.</p></div><div className="actions"><Button variant="primary" onClick={() => say("New API key: the secret is shown once")}>New API key</Button></div></div>
      <div className="grid two">
        <Card flush>
          <div className="card-head"><h2 className="h2">Principals</h2></div>
          <div className="grid-head" style={{ gridTemplateColumns: "1fr 1fr 1fr" }}><span>Name</span><span>Role</span><span>Last seen</span></div>
          {principals.loading && <div style={{ padding: 20 }}><Skeleton h={16} /></div>}
          {(principals.data ?? []).map(p => <div key={p.name} className="grid-row" style={{ gridTemplateColumns: "1fr 1fr 1fr", padding: "10px 20px" }}><span style={{ fontWeight: 600 }}>{p.name}</span><select aria-label={`Role of ${p.name}`} className="select" style={{ height: 28, width: 120 }} defaultValue={p.role} onChange={e => say(`${p.name} is now ${e.target.value}`)}>{["viewer", "builder", "reviewer", "admin"].map(r => <option key={r}>{r}</option>)}</select><span className="muted">{p.seen}</span></div>)}
        </Card>
        <div className="grid">
          <Card flush>
            <div className="card-head"><h2 className="h2">API keys</h2></div>
            {(keys.data ?? []).map(k => <div key={k.name} className="row between" style={{ padding: "10px 20px", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}><span><div style={{ fontWeight: 600 }}>{k.name}</div><div className="mono muted-2" style={{ fontSize: 11.5 }}>{k.prefix} · {k.role}</div></span><Button size="xs" variant="danger" style={{ height: 26 }} onClick={() => say(`Revoke ${k.name}?`)}>Revoke</Button></div>)}
          </Card>
          <Card flush>
            <div className="card-head"><h2 className="h2">Locks</h2></div>
            {(locks.data ?? []).map(l => <div key={l.what} className="row between" style={{ padding: "10px 20px", borderTop: "1px solid var(--line-2)", fontSize: 12.5 }}><span><strong style={{ fontWeight: 600 }}>{l.what}</strong> <span className="muted">held by {l.who}, expires in {l.exp}</span></span><Button size="xs" style={{ height: 26 }} onClick={() => say(`Released the lease on ${l.what}`)}>Force release</Button></div>)}
          </Card>
        </div>
      </div>
    </>
  );
}
