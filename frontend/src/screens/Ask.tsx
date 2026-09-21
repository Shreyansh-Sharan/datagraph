import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Icon } from "@/components/icons";
import { Button, Skeleton } from "@/components/ui";
import { useApp, useLoad } from "@/state/app";
import { answer, SUGGESTIONS, type AskAnswer, type AskLink } from "./askEngine";
import { askTerm, type  DomainSummary } from "@/api";

interface Turn extends AskAnswer { q: string }

/** Ask assistant. At home it spans all domains; inside a domain it is scoped to it. */
export function Ask({ inDomain, domains: given, domain: domainProp }: { inDomain?: boolean; domains?: DomainSummary[]; domain?: string }) {
  const { api, config } = useApp();
  const navigate = useNavigate();
  const { name: routeDomain } = useParams();
  const fixed = domainProp ?? (inDomain ? routeDomain : undefined);
  const [domainName, setDomainName] = useState(fixed ?? "rgm");
  const [q, setQ] = useState("");
  const [thread, setThread] = useState<Turn[]>([]);
  const loaded = useLoad(async () => {
    const domains = given ?? await api.domains();
    const dom = fixed ?? domainName;
    const d = domains.find(x => x.name === dom) ?? domains[0];
    const v = d?.versions[0]?.version ?? 0;
    const [glossary, classes, mapping] = d && v ? await Promise.all([api.glossary(d.name).then(es => es.map(askTerm)), api.ontology(d.name, v), api.mapping(d.name, v)]) : [[], [], {}];
    return { domains, glossary, classes, mapping };
  }, [given, fixed, domainName]);

  const currentDomain = fixed ?? domainName;
  const ask = (text: string) => {
    if (!loaded.data) return;
    const a = answer(text, { domain: currentDomain, domains: loaded.data.domains, glossary: loaded.data.glossary, classes: loaded.data.classes, mapping: loaded.data.mapping, sourceKind: config.sourceKind });
    setThread(t => [{ q: text, ...a }, ...t]);
  };
  const submit = (e: FormEvent) => { e.preventDefault(); const t = q.trim(); if (!t) return; ask(t); setQ(""); };
  const follow = (l: AskLink) => {
    if (l.screen === "tasks") return navigate("/tasks");
    const d = l.domain ?? currentDomain; const qs = new URLSearchParams(l.params ?? {}).toString();
    navigate(`/d/${encodeURIComponent(d)}/${l.screen}${qs ? `?${qs}` : ""}`);
  };

  return (
    <div style={{ maxWidth: 960, margin: "0 auto" }}>
      <div style={{ textAlign: "center", padding: "20px 0 18px" }}>
        <div style={{ display: "inline-flex", alignItems: "center", gap: 8, height: 26, padding: "0 12px", borderRadius: 999, background: "var(--blue-soft)", color: "var(--blue-dark)", fontSize: 11.5, fontWeight: 700, letterSpacing: ".04em", textTransform: "uppercase", marginBottom: 14 }}><i style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--yellow)" }} />P.AI assistant</div>
        <h1 style={{ fontSize: 34, fontWeight: 900, letterSpacing: "-.025em", lineHeight: 1.1, marginBottom: 8 }}>Ask <span style={{ color: "var(--blue)" }}>{inDomain ? currentDomain : "datagraph"}</span></h1>
        <p className="muted" style={{ maxWidth: "56ch", margin: "0 auto", fontSize: 14 }}>Look up a glossary term, find where to do something, or ask about a domain. Answers link straight to the right screen.</p>
      </div>
      <form onSubmit={submit} style={{ display: "flex", gap: 8, background: "#fff", border: "1px solid var(--grey-2)", borderRadius: 12, padding: "8px 8px 8px 16px", alignItems: "center" }}>
        <Icon name="search" size={18} stroke="#7A7A80" />
        <input id="ask-input" aria-label="Ask a question" value={q} onChange={e => setQ(e.target.value)} placeholder="e.g. What is net revenue? · Where do I map Channel? · Show hr domain" style={{ flex: 1, height: 38, border: 0, outline: 0, font: "400 14px var(--font)", color: "var(--ink)", background: "transparent" }} />
        {!fixed && <select aria-label="Domain" className="select filled" style={{ height: 34, borderRadius: 8 }} value={domainName} onChange={e => setDomainName(e.target.value)}>{(loaded.data?.domains ?? []).map(d => <option key={d.name} value={d.name}>{d.name}</option>)}</select>}
        <Button type="submit" variant="primary" style={{ borderRadius: 8 }}>Ask</Button>
      </form>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, margin: "12px 0 24px", justifyContent: "center" }}>
        {SUGGESTIONS.map(s => <Button key={s} size="sm" pill style={{ fontWeight: 500, color: "var(--ink-2)", borderColor: "var(--line)" }} onClick={() => ask(s)}>{s}</Button>)}
      </div>
      {loaded.loading && thread.length === 0 && <Skeleton h={0} />}
      {thread.map((a, i) => (
        <div key={i} style={{ marginBottom: 18 }}>
          <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 8 }}><span style={{ maxWidth: "70%", padding: "9px 14px", borderRadius: "12px 12px 2px 12px", background: "var(--ink)", color: "#fff", fontSize: 13 }}>{a.q}</span></div>
          <div style={{ display: "grid", gridTemplateColumns: "28px minmax(0,1fr)", gap: 10 }}>
            <span style={{ width: 28, height: 28, borderRadius: 8, background: "var(--blue)", color: "var(--yellow)", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 14 }}>★</span>
            <div style={{ background: "#fff", border: "1px solid var(--line)", borderRadius: "2px 12px 12px 12px", padding: "14px 16px" }}>
              <div style={{ fontSize: 13.5, lineHeight: 1.6 }}>{a.text}</div>
              {a.term && (
                <div style={{ marginTop: 12, padding: "12px 14px", borderRadius: 8, background: "var(--blue-soft)", border: "1px solid var(--blue-border)" }}>
                  <div className="row between" style={{ alignItems: "baseline" }}><strong style={{ fontSize: 14, fontWeight: 800 }}>{a.term.term}</strong><span className="muted" style={{ fontSize: 11 }}>Glossary · steward {a.term.steward} · {a.term.domain}</span></div>
                  <div style={{ fontSize: 13, color: "var(--ink-2)", margin: "4px 0 8px" }}>{a.term.def}</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6, fontSize: 11 }}>
                    <a href="#" className="pill solid" onClick={e => { e.preventDefault(); follow({ title: "", sub: "", icon: "", screen: "ontology", domain: a.term!.domain, params: { cls: a.term!.cls, view: "map" } }); }}>class {a.term.cls}</a>
                    {a.term.cols.map(c => <a key={c} href="#" className="pill outline mono" style={{ borderColor: "var(--blue-light)", color: "var(--blue-dark)", fontWeight: 400 }} onClick={e => { e.preventDefault(); follow({ title: "", sub: "", icon: "", screen: "metadata", domain: a.term!.domain, params: { table: a.term!.table, tab: "glossary", gq: a.term!.term } }); }}>{c}</a>)}
                  </div>
                </div>
              )}
              {a.links.length > 0 && (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))", gap: 8, marginTop: 12 }}>
                  {a.links.map(l => (
                    <a key={l.title} href="#" onClick={e => { e.preventDefault(); follow(l); }} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderRadius: 8, border: "1px solid var(--line)", color: "var(--ink)" }}>
                      <span style={{ width: 28, height: 28, borderRadius: 7, background: "var(--blue-soft)", color: "var(--blue)", display: "inline-flex", alignItems: "center", justifyContent: "center", flex: "none" }}><Icon name={l.icon} /></span>
                      <span style={{ minWidth: 0 }}><span style={{ display: "block", fontWeight: 700, fontSize: 12.5 }}>{l.title}</span><span className="muted" style={{ display: "block", fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.sub}</span></span>
                    </a>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
