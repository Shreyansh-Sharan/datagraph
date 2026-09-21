import { useState } from "react";
import { Button, Card, Pill, Skeleton } from "@/components/ui";
import { useApp, useLoad } from "@/state/app";
import { useDomain, useGo } from "@/state/domain";
import type { TripleQuery } from "@/api";

const COLS = "1.6fr 1.2fr 1.8fr .6fr";
const DARK = "#1636E0";

export function Triples() {
  const { api } = useApp();
  const { domain } = useDomain();
  const go = useGo();
  const [query, setQuery] = useState<TripleQuery>({ q: "", filter: "all", sort: "subject", dir: "asc", limit: 100, offset: 0 });
  const status = useLoad(() => api.graphStatus(domain.name), [domain.name]);
  const page = useLoad(() => api.triples(domain.name, query), [domain.name, JSON.stringify(query)]);
  const set = (patch: Partial<TripleQuery>) => setQuery(q => ({ ...q, offset: 0, ...patch }));
  const sortBy = (col: TripleQuery["sort"]) => set(query.sort === col ? { dir: query.dir === "asc" ? "desc" : "asc" } : { sort: col, dir: "asc" });
  const rows = page.data?.rows ?? [];
  const entityOf = (iri: string) => iri;   // Explore takes the full IRI
  const headers: [TripleQuery["sort"], string][] = [["subject", "Subject"], ["predicate", "Predicate"], ["object", "Object"], ["inferred", "Inferred"]];

  return (
    <>
      <div className="page-head" style={{ marginBottom: 16 }}>
        <div><h1>Triples</h1><p>{status.data?.triples ?? "—"} triples · {status.data?.inferred ?? "—"} inferred · showing {rows.length}</p></div>
        <div className="actions">
          <input aria-label="Filter text" className="input sm" style={{ width: 220 }} placeholder="Filter text" value={query.q} onChange={e => set({ q: e.target.value })} />
          {(["all", "asserted", "inferred"] as const).map(f => <Button key={f} size="sm" style={{ height: 32 }} active={query.filter === f} onClick={() => set({ filter: f })}>{f[0].toUpperCase() + f.slice(1)}</Button>)}
          <select aria-label="Page size" className="select sm" value={query.limit} onChange={e => set({ limit: Number(e.target.value) })}><option value={100}>100 / page</option><option value={500}>500 / page</option><option value={1000}>1000 / page</option></select>
        </div>
      </div>
      <Card flush>
        <div style={{ display: "grid", gridTemplateColumns: COLS, background: "var(--surface-3)" }}>
          {headers.map(([id, label]) => { const on = query.sort === id; return <button key={id} type="button" aria-sort={on ? (query.dir === "asc" ? "ascending" : "descending") : "none"} onClick={() => sortBy(id)} style={{ textAlign: "left", padding: "10px 16px", border: 0, background: "transparent", font: "700 11px var(--font)", letterSpacing: ".06em", textTransform: "uppercase", color: on ? DARK : "var(--muted)", cursor: "pointer", display: "flex", gap: 6, alignItems: "center" }}>{label}<span style={{ fontSize: 10 }}>{on ? (query.dir === "asc" ? "▲" : "▼") : ""}</span></button>; })}
        </div>
        {page.loading && <div style={{ padding: 16 }}><Skeleton h={14} /><Skeleton h={14} /><Skeleton h={14} /></div>}
        {rows.map((t, i) => (
          <div key={i} className="grid-row hover mono" style={{ gridTemplateColumns: COLS, padding: "8px 16px", fontSize: 12 }}>
            <a href="#" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} onClick={e => { e.preventDefault(); go("explore", { entity: entityOf(t.s) }); }}>{t.s}</a>
            <span style={{ color: "var(--ink-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.p}</span>
            <span className="row" style={{ minWidth: 0 }}>{t.isIri ? <a href="#" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} onClick={e => { e.preventDefault(); go("explore", { entity: entityOf(t.o) }); }}>{t.o}</a> : <><span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.o}</span><span className="muted-3" style={{ fontSize: 10, flex: "none" }}>{t.dt}</span></>}</span>
            <span>{t.inferred ? <Pill tone="warn" style={{ height: 18, fontSize: 10, fontFamily: "var(--font)" }}>inferred</Pill> : <span style={{ font: "600 11px var(--font)", color: "var(--muted-3)" }}>asserted</span>}</span>
          </div>
        ))}
        {!page.loading && rows.length === 0 && <p className="muted" style={{ padding: 20 }}>No triples match. Loosen the filters.</p>}
        <div className="row between muted small" style={{ padding: "10px 16px", borderTop: "1px solid var(--line)" }}>
          <span>Rows {rows.length ? query.offset + 1 : 0}–{query.offset + rows.length} of {page.data?.total ?? "—"}</span>
          <div className="row" style={{ gap: 6 }}><Button size="sm" style={{ height: 26 }} disabled={query.offset === 0} onClick={() => setQuery(q => ({ ...q, offset: Math.max(0, q.offset - q.limit) }))}>Previous</Button><Button size="sm" style={{ height: 26 }} disabled={rows.length < query.limit} onClick={() => setQuery(q => ({ ...q, offset: q.offset + q.limit }))}>Next</Button></div>
        </div>
      </Card>
    </>
  );
}
