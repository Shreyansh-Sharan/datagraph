import { Button, Card, Dot, Glyph, Label, Pill, Skeleton, Tabs } from "@/components/ui";
import { Stage, StageTools, glyphOf, type StageEdge, type StageNode } from "@/components/Stage";
import { useApp, useLoad } from "@/state/app";
import { useDomain, useGo, useParam } from "@/state/domain";

type View = "map" | "list" | "checks";
const BLUE = "#2249FF", ORANGE = "#FF7000", DARK = "#1636E0";

export function Ontology() {
  const { api, say } = useApp();
  const { domain, version, editable } = useDomain();
  const go = useGo();
  const [view, setView] = useParam("view", "map");
  const [clsId, setCls] = useParam("cls", "Customer");
  const classes = useLoad(() => api.ontology(domain.name, version!.version), [domain.name, version?.version]);
  const checks = useLoad(() => api.ontologyChecks(domain.name, version!.version), [domain.name, version?.version]);
  const list = classes.data ?? [];
  const sel = list.find(c => c.id === clsId) ?? list[0];
  const edges: StageEdge[] = list.flatMap(c => [
    ...c.parents.map(p => ({ from: c.id, to: p, label: "is a", color: ORANGE, dashed: true, labelColor: "#B84F00" })),
    ...c.rels.map(r => { const hot = sel && (c.id === sel.id || r.target === sel.id); return { from: c.id, to: r.target, label: r.name, color: hot ? BLUE : "#B9C4FF", width: hot ? 2 : 1.5, labelColor: hot ? DARK : "#7A7A80" }; }),
  ]);
  const nodes: StageNode[] = list.map(c => ({ id: c.id, label: c.id, glyph: glyphOf(c.id), x: c.x, y: c.y, fill: c.id === sel?.id ? BLUE : "#8FA1FF", border: "#D4DCFF", selected: c.id === sel?.id, props: c.attrs.length + c.rels.length, title: c.iri }));

  return (
    <>
      <div className="page-head">
        <div><h1>Ontology</h1><p>{list.length} classes, {edges.length} relationships. Click a class to edit it.</p></div>
        <div className="actions"><Button onClick={() => say("Import an ontology file (Turtle, JSON-LD, RDF/XML)")}>Import</Button><Button onClick={() => say("Drafting with AI from the metadata snapshot…")}>Draft with AI</Button><Button variant="primary" onClick={() => say("Drafted from tables: keys inferred, icons assigned")}>Draft from tables</Button></div>
      </div>
      <div style={{ marginBottom: 14 }}><Tabs<View> value={(view as View) || "map"} onChange={v => setView(v)} items={[{ id: "map", label: "Map" }, { id: "list", label: "Classes" }, { id: "checks", label: `Checks · ${checks.data?.length ?? 0}` }]} /></div>
      {classes.loading && <Skeleton h={520} />}
      {view === "map" && sel && (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 340px", gap: 20, alignItems: "start" }}>
          <Stage nodes={nodes} edges={edges} height={520} dotted onSelect={id => setCls(id)}
            tools={<StageTools onAction={t => say(t)} />}
            legend={<><span><i style={{ width: 18, height: 2, background: "#8FA1FF" }} />relationship</span><span><i style={{ width: 18, height: 0, borderTop: "2px dashed #FF7000" }} />inheritance</span></>}
            status={`${list.length} nodes · ${edges.length} edges`} />
          <Card>
            <div className="row" style={{ gap: 10, marginBottom: 4 }}><Glyph size={28} fontSize={12}>{glyphOf(sel.id)}</Glyph><h2 style={{ fontSize: 17, fontWeight: 800 }}>{sel.id}</h2></div>
            <div className="mono" style={{ fontSize: 11, color: "var(--muted-2)", marginBottom: 14, wordBreak: "break-all" }}>{sel.iri}</div>
            <Label>Description</Label>
            <textarea id="cls-desc" className="textarea full" rows={2} defaultValue={sel.desc} key={sel.id} disabled={!editable} style={{ marginBottom: 12 }} />
            <Label>Parents</Label>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 14 }}>{sel.parents.map(p => <Pill key={p} tone="blue" size="lg" style={{ height: 24, fontSize: 12 }}>{p}</Pill>)}{editable && <Button dashed onClick={() => say("Pick a parent class")}>+ Add parent</Button>}</div>
            <div className="row between" style={{ alignItems: "baseline" }}><Label block={false}>Attributes</Label>{editable && <a href="#" className="small" style={{ fontWeight: 600 }} onClick={e => { e.preventDefault(); say("Add attribute"); }}>+ Add</a>}</div>
            {sel.attrs.map(a => <div key={a.name} className="row between" style={{ padding: "7px 0", borderBottom: "1px solid var(--line-2)", fontSize: 12.5 }}><span>{a.name}</span><span className="mono" style={{ fontSize: 11, color: "var(--muted-2)" }}>{a.range}</span></div>)}
            <div className="row between" style={{ alignItems: "baseline", marginTop: 14 }}><Label block={false}>Relationships</Label>{editable && <a href="#" className="small" style={{ fontWeight: 600 }} onClick={e => { e.preventDefault(); say("Add relationship"); }}>+ Add</a>}</div>
            {sel.rels.map(r => <div key={r.name} className="row between" style={{ padding: "7px 0", borderBottom: "1px solid var(--line-2)", fontSize: 12.5 }}><span>{r.name}</span><span className="muted">→ {r.target}</span></div>)}
            {sel.rels.length === 0 && <p className="muted-2" style={{ fontSize: 12.5, margin: "8px 0" }}>No relationships from this class.</p>}
            {editable && <div className="row" style={{ marginTop: 16 }}><Button variant="primary" size="sm" style={{ flex: 1, height: 32 }} onClick={() => say(`Saved ${sel.id}`)}>Save class</Button><Button size="sm" variant="danger" style={{ height: 32 }} onClick={() => say(`Type ${sel.id} to confirm deletion`)}>Delete</Button></div>}
          </Card>
        </div>
      )}
      {view === "list" && (
        <Card flush>
          <div className="grid-head" style={{ gridTemplateColumns: "1.2fr 2.4fr 1fr .8fr .8fr", padding: "10px 20px" }}><span>Class</span><span>Description</span><span>Parents</span><span>Attributes</span><span>Relations</span></div>
          {list.map(c => (
            <a key={c.id} href="#" className="grid-row link" style={{ gridTemplateColumns: "1.2fr 2.4fr 1fr .8fr .8fr" }} onClick={e => { e.preventDefault(); setCls(c.id); setView("map"); }}>
              <span className="row" style={{ fontWeight: 700 }}><Glyph size={22} fontSize={10}>{glyphOf(c.id)}</Glyph>{c.id}</span>
              <span className="muted" style={{ fontSize: 12.5 }}>{c.desc}</span><span className="muted" style={{ fontSize: 12.5 }}>{c.parents.join(", ") || "—"}</span><span>{c.attrs.length}</span><span>{c.rels.length}</span>
            </a>
          ))}
        </Card>
      )}
      {view === "checks" && (
        <Card flush>
          <div className="grid-head" style={{ gridTemplateColumns: ".7fr 1.2fr 1fr 3fr", padding: "10px 20px" }}><span>Severity</span><span>Code</span><span>Subject</span><span>Message</span></div>
          {(checks.data ?? []).map(k => (
            <a key={k.code + k.subject} href="#" className="grid-row link" style={{ gridTemplateColumns: ".7fr 1.2fr 1fr 3fr" }} onClick={e => { e.preventDefault(); if (k.target.screen === "ontology") { setCls(k.target.cls); setView("map"); } else go("mapping", { cls: k.target.cls }); }}>
              <span className="row"><Dot color={k.severity === "warning" ? ORANGE : k.severity === "error" ? "#B84F00" : "#B3B3B7"} />{k.severity}</span><span className="mono" style={{ fontSize: 11.5 }}>{k.code}</span><span style={{ fontWeight: 600 }}>{k.subject}</span><span style={{ color: "var(--ink-2)" }}>{k.message}</span>
            </a>
          ))}
          {checks.data?.length === 0 && <p className="muted" style={{ padding: 20 }}>No issues. The ontology is consistent.</p>}
        </Card>
      )}
    </>
  );
}
