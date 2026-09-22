// Spotlight: a translucent palette over any screen (Cmd+K, Ctrl+K) where you jump to a screen or
// ask the assistant, which answers through the MCP tools and shows what it called.
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "@/components/icons";
import { Spinner } from "@/components/ui";
import { useApp } from "@/state/app";
import { useAssistantContext } from "@/state/assistant";
import type { ChatEvent, ToolTrace } from "@/api";

const SCREENS: [string, string, string][] = [["overview", "Overview", "Status, lifecycle and what to do next"], ["metadata", "Metadata", "Tables of the source and the snapshot"],
  ["ontology", "Ontology", "Classes and relationships"], ["mapping", "Mapping", "Classes onto tables"], ["build", "Build", "Load the graph from the source"],
  ["explore", "Explore", "Walk the graph"], ["triples", "Triples", "Every statement of the graph"], ["ask", "Ask", "The assistant and your threads"]];

export const isSpotlightKey = (e: KeyboardEvent) => (e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === "k";

export function Spotlight() {
  const { api } = useApp();
  const ctx = useAssistantContext();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [asked, setAsked] = useState<string | null>(null);
  const [answer, setAnswer] = useState<string | null>(null);
  const [tools, setTools] = useState<ToolTrace[]>([]);
  const [live, setLive] = useState<string | null>(null);
  const [conversation, setConversation] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isSpotlightKey(e)) { e.preventDefault(); setOpen(o => !o); }
      else if (e.key === "Escape" && open) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  useEffect(() => { if (open) setTimeout(() => input.current?.focus(), 0); else { setQ(""); setAsked(null); setAnswer(null); setTools([]); setLive(null); setError(null); setConversation(null); } }, [open]);

  const t = q.trim().toLowerCase();
  const jumps = ctx.domain && t ? SCREENS.filter(([id, label]) => id.includes(t) || label.toLowerCase().includes(t)) : [];
  const go = (screen: string) => { navigate(`/d/${encodeURIComponent(ctx.domain!)}/${screen}${ctx.version ? `?v=${ctx.version}` : ""}`); setOpen(false); };
  const ask = async (text: string) => {
    if (!text.trim() || busy) return;
    setBusy(true); setAsked(text); setAnswer(null); setTools([]); setLive("Thinking…"); setError(null);
    try {
      const r = await api.chat(text, ctx, conversation, (e: ChatEvent) => {
        if (e.type === "tool_call") setLive(`Calling ${e.name}…`);
        if (e.type === "tool_result") setTools(ts => [...ts, { id: e.id, name: e.name, arguments: {}, result: e.result }]);
        if (e.type === "text") { setAnswer(e.text); setLive(null); }
      });
      setAnswer(r.answer); setTools(r.tools); setConversation(r.conversation_id); setLive(null); setQ("");
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); setLive(null); }
    finally { setBusy(false); }
  };
  if (!open) return null;
  return (
    <div className="spot-backdrop" onMouseDown={() => setOpen(false)} data-testid="spotlight">
      <div className="spot" role="dialog" aria-modal="true" aria-label="Spotlight" onMouseDown={e => e.stopPropagation()}>
        <form className="spot-input" onSubmit={e => { e.preventDefault(); if (jumps.length && !q.includes(" ") && !asked) go(jumps[0][0]); else void ask(q); }}>
          <Icon name="ask" size={16} stroke="var(--blue)" />
          <input ref={input} aria-label="Ask the assistant" placeholder={ctx.domain ? `Ask about ${ctx.domain}${ctx.table ? ` · ${ctx.table.split(".").pop()}` : ""}, or type a screen name` : "Ask the assistant"} value={q} onChange={e => setQ(e.target.value)} disabled={busy} />
          {busy ? <Spinner blue /> : <kbd>esc</kbd>}
        </form>
        {!asked && jumps.length > 0 && (
          <ul className="spot-list" role="listbox" aria-label="Screens">
            {jumps.map(([id, label, sub]) => <li key={id}><button type="button" role="option" aria-selected={false} onClick={() => go(id)}><Icon name={id === "ask" ? "ask" : id} size={14} /><span><b>{label}</b><span className="muted-2"> · {sub}</span></span><kbd>↵</kbd></button></li>)}
          </ul>
        )}
        {!asked && t && <div className="spot-hint"><button type="button" className="spot-ask" onClick={() => void ask(q)}>Ask the assistant: <b>{q}</b></button></div>}
        {!asked && !t && <div className="spot-hint muted">{ctx.domain ? `In ${ctx.domain}${ctx.screen ? ` · ${ctx.screen}` : ""}. Ask about tables, rules, the graph, or say what to run.` : "Ask about a domain, or open one first to act on it."}</div>}
        {asked && (
          <div className="spot-answer" aria-live="polite">
            <div className="spot-q">{asked}</div>
            {tools.length > 0 && <div className="spot-tools">{tools.map(x => <span key={x.id} className="pill outline mono" title={x.result.slice(0, 400)}>{x.name}</span>)}</div>}
            {live && <div className="muted small row" style={{ gap: 8 }}><Spinner blue />{live}</div>}
            {error && <div className="notice error">{error}</div>}
            {answer && <div className="spot-a">{answer}</div>}
            {answer && conversation && <div className="spot-foot"><button type="button" className="btn sm" onClick={() => { navigate(ctx.domain ? `/d/${encodeURIComponent(ctx.domain)}/ask?c=${conversation}` : `/?c=${conversation}`); setOpen(false); }}>Continue in Ask</button><span className="muted small">Type to ask a follow-up</span></div>}
          </div>
        )}
      </div>
    </div>
  );
}
