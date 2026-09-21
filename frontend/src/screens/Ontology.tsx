import { useEffect, useState } from "react";
import { Button, Card, Dialog, Dot, ErrorNotice, Glyph, Label, Pill, Skeleton, Spinner, Tabs } from "@/components/ui";
import type { AiProgress, SnapshotTable } from "@/api";
import { Stage, colorFor, glyphOf, type StageEdge, type StageGroup, type StageNode } from "@/components/Stage";
import { useApp, useLoad } from "@/state/app";
import { useDomain, useGo, useParam } from "@/state/domain";

type View = "map" | "list" | "checks";
const BLUE = "#2249FF", ORANGE = "#FF7000", DARK = "#1636E0";

export function Ontology() {
  const { api, say } = useApp();
  const { domain, version, editable } = useDomain();
  const go = useGo();
  const [view, setView] = useParam("view", "map");
  const [clsId, setCls] = useParam("cls", "");
  const classes = useLoad(() => api.ontology(domain.name, version!.version).catch(e => { if (/no ontology/i.test(String(e))) return []; throw e; }), [domain.name, version?.version]);
  const checks = useLoad(() => api.ontologyChecks(domain.name, version!.version).catch(() => []), [domain.name, version?.version]);
  const [draft, setDraft] = useState<"ai" | "tables" | null>(null);
  const [running, setRunning] = useState<{ progress: string; since: number } | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => { if (!running) return; const t = setInterval(() => setTick(x => x + 1), 1000); return () => clearInterval(t); }, [running]);
  // A draft started earlier (the dialog was closed, or another tab) is still running on the server: show it, reload when it ends.
  useEffect(() => {
    let alive = true;
    api.runningAiJob(domain.name, version!.version, "draft-ontology", p => { if (alive) setRunning({ progress: p.progress, since: p.startedAt ? new Date(p.startedAt).getTime() : Date.now() }); })
      .then(end => { if (!alive || !end) return; setRunning(null); classes.reload(); checks.reload(); say(end.status === "succeeded" ? "AI draft finished: ontology replaced" : `AI draft failed: ${end.progress}`); })
      .catch(() => { /* status is a courtesy */ });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [domain.name, version?.version]);
  const runningFor = running ? Math.max(0, Math.round((Date.now() - running.since) / 1000)) : 0;
  void tick;
  const list = classes.data ?? [];
  const drafted = (r: { classes: number; properties: number; warnings: number }) => { classes.reload(); checks.reload(); setDraft(null); say(`Drafted ${r.classes} classes and ${r.properties} properties${r.warnings ? ` · ${r.warnings} warning${r.warnings === 1 ? "" : "s"} to review` : ""}`); };
  const sel = list.find(c => c.id === clsId) ?? list[0];
  const edges: StageEdge[] = list.flatMap(c => [
    ...c.parents.map(p => ({ from: c.id, to: p, label: "is a", color: ORANGE, dashed: true, labelColor: "#B84F00" })),
    ...c.rels.map(r => { const hot = sel && (c.id === sel.id || r.target === sel.id); return { from: c.id, to: r.target, label: r.name, color: hot ? BLUE : "#B9C4FF", width: hot ? 2 : 1.5, labelColor: hot ? DARK : "#7A7A80" }; }),
  ]);
  // Colour by hierarchy when there is one (the root class each class descends from), else by name.
  const rootOf = (id: string, seen = new Set<string>()): string => { const c = list.find(x => x.id === id); const p = c?.parents.find(x => list.some(y => y.id === x)); return !p || seen.has(p) ? id : rootOf(p, seen.add(id)); };
  const roots = Object.fromEntries(list.map(c => [c.id, rootOf(c.id)]));
  const rootCount = new Set(Object.values(roots)).size;
  const hierarchical = rootCount < list.length && rootCount <= 12;   // a legend of dozens of roots would not help
  const groups: StageGroup[] | undefined = hierarchical ? [...new Set(Object.values(roots))].sort().map(r => ({ id: r, label: r, color: colorFor(r) })) : undefined;
  const nodes: StageNode[] = list.map(c => ({ id: c.id, label: c.id, glyph: glyphOf(c.id), x: c.x, y: c.y, fill: colorFor(hierarchical ? roots[c.id] : c.id), border: c.id === sel?.id ? BLUE : undefined, selected: c.id === sel?.id, props: c.attrs.length + c.rels.length, title: c.iri, group: hierarchical ? roots[c.id] : undefined }));

  return (
    <>
      <div className="page-head">
        <div><h1>Ontology</h1><p>{list.length} classes, {edges.length} relationships. Click a class to edit it.</p></div>
        <div className="actions"><Button onClick={() => say("Import an ontology file (Turtle, JSON-LD, RDF/XML)")}>Import</Button><Button disabled={!editable} title={editable ? undefined : "Take the lease on a draft to change the ontology"} onClick={() => setDraft("ai")}>Draft with AI</Button><Button variant="primary" disabled={!editable} title={editable ? undefined : "Take the lease on a draft to change the ontology"} onClick={() => setDraft("tables")}>Draft from tables</Button></div>
      </div>
      <div style={{ marginBottom: 14 }}><Tabs<View> value={(view as View) || "map"} onChange={v => setView(v)} items={[{ id: "map", label: "Map" }, { id: "list", label: "Classes" }, { id: "checks", label: `Checks · ${checks.data?.length ?? 0}` }]} /></div>
      {running && <div className="notice" role="status" aria-live="polite" style={{ marginBottom: 14 }}><div className="row" style={{ gap: 8, fontWeight: 600 }}><Spinner blue />Drafting the ontology with AI · {running.progress} · {runningFor >= 60 ? `${Math.floor(runningFor / 60)} min ${runningFor % 60} s` : `${runningFor} s`}</div><div className="muted xs" style={{ marginTop: 4 }}>The map below is the current ontology; it is replaced when the draft finishes.</div></div>}
      {classes.loading && <Skeleton h={520} />}
      {classes.error && <ErrorNotice error={classes.error} />}
      {!classes.loading && !classes.error && list.length === 0 && (
        <Card className="dashed" style={{ textAlign: "center", padding: 32 }}>
          <div style={{ fontSize: 16, fontWeight: 800, marginBottom: 6 }}>No ontology yet</div>
          <p className="muted" style={{ marginBottom: 14 }}>Draft it with the AI connection from the tables in the snapshot, or derive classes from the tables directly and refine them here.</p>
          {editable && <div className="row" style={{ justifyContent: "center" }}><Button variant="primary" onClick={() => setDraft("ai")}>Draft with AI</Button><Button onClick={() => setDraft("tables")}>Draft from tables</Button></div>}
        </Card>
      )}
      <DraftDialog mode={draft} existing={list.length} onClose={() => setDraft(null)} onDraft={async (opts, onProgress) => drafted(await api.draftOntology(domain.name, version!.version, opts, onProgress))} tables={() => api.snapshot(domain.name, version!.version)} />
      {view === "map" && sel && (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 340px", gap: 20, alignItems: "start" }}>
          <Stage nodes={nodes} edges={edges} height={640} dotted groups={groups} onSelect={id => setCls(id)} onExpand={id => { setCls(id); setView("map"); }}
            legend={<><span><i style={{ width: 18, height: 2, background: "#8FA1FF" }} />relationship</span><span><i style={{ width: 18, height: 0, borderTop: "2px dashed #FF7000" }} />inheritance</span></>}
            />
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


/** Pick the snapshot tables (and, for AI, describe the domain) before replacing the draft's ontology. */
function DraftDialog({ mode, existing, onClose, onDraft, tables }: { mode: "ai" | "tables" | null; existing: number; onClose: () => void; onDraft: (opts: { ai: boolean; description?: string; tables: string[] }, onProgress: (p: AiProgress) => void) => Promise<void>; tables: () => Promise<SnapshotTable[]> }) {
  const { say } = useApp();
  const snap = useLoad(() => mode ? tables().catch(() => [] as SnapshotTable[]) : Promise.resolve(null), [mode]);
  const [off, setOff] = useState<string[]>([]);
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [since, setSince] = useState<number | null>(null);
  const [stage, setStage] = useState<string | null>(null);
  const [now, setNow] = useState(0);
  useEffect(() => { if (since === null) return; const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, [since]);
  const all = snap.data ?? [];
  const chosen = all.map(t => t.table).filter(t => !off.includes(t));
  const run = async () => { setBusy(true); setSince(Date.now()); setStage(null); try { await onDraft({ ai: mode === "ai", description, tables: chosen }, p => setStage(p.progress)); setOff([]); } catch (e) { say(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); setSince(null); setStage(null); } };
  const elapsed = since ? Math.max(0, Math.round(((now || since) - since) / 1000)) : 0;
  return (
    <Dialog title={mode === "ai" ? "Draft the ontology with AI" : "Draft the ontology from tables"} open={mode !== null} onClose={onClose} width={520}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={busy || chosen.length === 0} onClick={run}>{busy && <Spinner />}Draft ontology</Button></>}>
      {existing > 0 && <div className="notice" style={{ marginBottom: 12 }}><strong style={{ fontWeight: 700 }}>This replaces the current {existing} classes.</strong> The mapping keeps bindings whose classes still exist.</div>}
      {mode === "ai" && <><Label>What this domain is about</Label><textarea className="textarea full" rows={2} aria-label="What this domain is about" placeholder="e.g. Customers, their orders and the products they buy" value={description} onChange={e => setDescription(e.target.value)} style={{ width: "100%", marginBottom: 12 }} /></>}
      <Label>Tables from the snapshot</Label>
      {snap.loading && <Skeleton h={60} />}
      {snap.data && all.length === 0 && <p className="muted small">The snapshot is empty. Import tables on the Metadata screen first.</p>}
      <div style={{ maxHeight: 220, overflowY: "auto" }}>
        {all.map(t => <label key={t.table} className="row" style={{ gap: 8, padding: "5px 0", fontSize: 12.5 }}><input type="checkbox" checked={!off.includes(t.table)} onChange={e => setOff(o => (e.target.checked ? o.filter(x => x !== t.table) : [...o, t.table]))} /><span className="mono" style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{t.table}</span><span className="muted-2 xs" style={{ marginLeft: "auto" }}>{t.columns} cols</span></label>)}
      </div>
      {busy
        ? <div className="notice" style={{ marginTop: 10 }}><div className="row" style={{ gap: 8, fontWeight: 600 }}><Spinner blue />{stage ?? `Reading ${chosen.length} table${chosen.length === 1 ? "" : "s"} from the source, then asking the AI`} · {elapsed} s</div><div className="muted xs" style={{ marginTop: 4 }}>A few tables take about 15 seconds; dozens take a few minutes. Keep this dialog open.</div></div>
        : <div className="muted-2 xs" style={{ marginTop: 8 }}>{mode === "ai" ? "The AI connection reads the columns, keys and comments of these tables and proposes classes, attributes and relationships." : "One class per table, attributes from columns, relationships from foreign keys; keys are inferred where the catalog has none."}{chosen.length > 20 && <> <strong style={{ color: "var(--orange-text)" }}>{chosen.length} tables selected: expect a few minutes, and a very large ontology.</strong></>}</div>}
    </Dialog>
  );
}
