// Ask: the assistant's conversation. It answers through the MCP tools, shows what it called,
// acts where you ask it to (build, profile, rules), and keeps every thread.
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Icon } from "@/components/icons";
import { Markdown } from "@/components/Markdown";
import { Button, Skeleton, Spinner } from "@/components/ui";
import { useApp, useLoad } from "@/state/app";
import { useAssistantContext } from "@/state/assistant";
import { relTime } from "@/api/format";
import type { ChatEvent, ChatMessage, Conversation, DomainSummary, ToolTrace } from "@/api";

const SUGGESTIONS = ["What is in this domain?", "Chart sales by year", "Why is the largest region inconsistent?", "Which rules are failing?", "Add the relationship the tables carry but the ontology lacks", "Start a build"];
type Turn = { id: string; role: "user" | "assistant"; text: string; tools: ToolTrace[]; pending?: boolean; live?: string | null; error?: string | null };

/** At home it spans every domain; inside a domain it is scoped to it (the context travels with each question). */
export function Ask({ inDomain, domain: domainProp }: { inDomain?: boolean; domains?: DomainSummary[]; domain?: string }) {
  const { api } = useApp();
  const navigate = useNavigate();
  const { name: routeDomain } = useParams();
  const [sp, setSp] = useSearchParams();
  const base = useAssistantContext();
  const ctx = { ...base, domain: domainProp ?? (inDomain ? routeDomain : undefined) ?? base.domain };
  const conversationId = sp.get("c");
  const [q, setQ] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const threads = useLoad(() => api.conversations(ctx.domain), [ctx.domain]);
  const thread = useLoad(() => conversationId ? api.conversation(conversationId) : Promise.resolve(null), [conversationId]);

  useEffect(() => {   // an opened thread is shown as turns: each assistant answer with the tools it called just before
    if (!conversationId) { setTurns([]); return; }
    if (!thread.data) return;
    setTurns(fold(thread.data.messages));
  }, [conversationId, thread.data]);
  useEffect(() => { bottom.current?.scrollIntoView?.({ block: "end" }); }, [turns]);

  const ask = async (text: string) => {
    const message = text.trim();
    if (!message || busy) return;
    setBusy(true); setQ("");
    const id = `t-${Date.now()}`;
    setTurns(ts => [...ts, { id: `${id}-q`, role: "user", text: message, tools: [] }, { id, role: "assistant", text: "", tools: [], pending: true, live: "Thinking…" }]);
    const patch = (p: Partial<Turn>) => setTurns(ts => ts.map(t => (t.id === id ? { ...t, ...p } : t)));
    try {
      const r = await api.chat(message, ctx, conversationId, (e: ChatEvent) => {
        if (e.type === "tool_call") patch({ live: `Calling ${e.name}…` });
        if (e.type === "tool_result") setTurns(ts => ts.map(t => (t.id === id ? { ...t, tools: [...t.tools, { id: e.id, name: e.name, arguments: {}, result: e.result }] } : t)));
        if (e.type === "text") patch({ text: e.text, live: null });
      });
      patch({ text: r.answer, tools: r.tools, pending: false, live: null });
      if (!conversationId) { setSp(prev => { const n = new URLSearchParams(prev); n.set("c", r.conversation_id); return n; }, { replace: true }); }
      threads.reload();
    } catch (e) { patch({ pending: false, live: null, error: e instanceof Error ? e.message : String(e) }); }
    finally { setBusy(false); }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); void ask(q); };
  const openThread = (c: Conversation | null) => setSp(prev => { const n = new URLSearchParams(prev); if (c) n.set("c", c.id); else n.delete("c"); return n; });
  const remove = async (c: Conversation) => { await api.deleteConversation(c.id); if (c.id === conversationId) openThread(null); threads.reload(); };

  return (
    <div className="chat">
      <aside className="chat-threads" aria-label="Conversations">
        <Button variant="primary" size="sm" style={{ width: "100%", justifyContent: "center" }} onClick={() => openThread(null)}>New conversation</Button>
        {threads.loading && !threads.data && <Skeleton h={40} style={{ marginTop: 10 }} />}
        <ul>
          {(threads.data ?? []).map(c => (
            <li key={c.id} className={c.id === conversationId ? "on" : ""}>
              <button type="button" onClick={() => openThread(c)}><span className="ttl">{c.title}</span><span className="muted-3 xs">{c.domain ?? "all domains"} · {relTime(c.updated_at)}</span></button>
              <button type="button" className="chip-act" aria-label={`Delete conversation ${c.title}`} onClick={() => void remove(c)}>×</button>
            </li>))}
        </ul>
        {threads.data?.length === 0 && <p className="muted small" style={{ padding: "10px 8px" }}>No conversation yet. Your threads stay here.</p>}
      </aside>
      <section className="chat-main">
        <div className="chat-head">
          <div><h1>Ask <span style={{ color: "var(--blue)" }}>{ctx.domain ?? "datagraph"}</span></h1><p className="muted">The assistant answers through the graph and the source, and can act: profile a table, run or add rules, start a build. It says which tools it used.</p></div>
          <span className="muted small" title="Cmd+K or Ctrl+K opens the same assistant over any screen">Anywhere: <kbd>⌘K</kbd></span>
        </div>
        <div className="chat-log" role="log" aria-label="Conversation">
          {turns.length === 0 && !thread.loading && (
            <div className="chat-empty">
              <div className="ic"><Icon name="ask" size={18} /></div>
              <p className="muted">Ask about a table, a rule, an entity or the graph, or say what to run.</p>
              <div className="chat-sugg">{SUGGESTIONS.map(s => <button key={s} type="button" className="btn sm pill" onClick={() => void ask(s)}>{s}</button>)}</div>
            </div>
          )}
          {thread.loading && turns.length === 0 && <Skeleton h={80} />}
          {turns.map(t => (
            <div key={t.id} className={`msg ${t.role}`}>
              {t.role === "assistant" && t.tools.length > 0 && (
                <details className="tools"><summary>Used {t.tools.length} tool{t.tools.length === 1 ? "" : "s"}: {t.tools.map(x => x.name).join(", ")}</summary>
                  {t.tools.map(x => <div key={x.id} className="tool"><div className="mono small"><b>{x.name}</b>{Object.keys(x.arguments).length ? ` ${JSON.stringify(x.arguments)}` : ""}</div><pre>{x.result}</pre></div>)}
                </details>)}
              {t.live && <div className="muted small row" style={{ gap: 8 }}><Spinner blue />{t.live}</div>}
              {t.error && <div className="notice error">{t.error}</div>}
              {t.text && <div className="chat-bubble">{t.role === "assistant" ? <Markdown text={t.text} /> : t.text}</div>}
            </div>))}
          <div ref={bottom} />
        </div>
        <form className="chat-compose" onSubmit={submit}>
          <input aria-label="Ask a question" placeholder={ctx.domain ? `Ask about ${ctx.domain}…` : "Ask about a domain…"} value={q} onChange={e => setQ(e.target.value)} disabled={busy} />
          <Button type="submit" variant="primary" disabled={busy || !q.trim()}>{busy ? <Spinner /> : null}Ask</Button>
        </form>
        {ctx.domain && <p className="muted xs" style={{ margin: "6px 2px 0" }}>Context sent with each question: {ctx.domain}{ctx.version ? ` v${ctx.version}` : ""}{ctx.screen ? ` · ${ctx.screen}` : ""}{ctx.table ? ` · ${ctx.table}` : ""}. <a href="#" onClick={e => { e.preventDefault(); navigate("/ask"); }}>Ask across domains</a></p>}
      </section>
    </div>
  );
}

/** Stored messages into turns: each assistant answer carries the tool calls made right before it. */
function fold(messages: ChatMessage[]): Turn[] {
  const out: Turn[] = [];
  let pending: ToolTrace[] = [];
  const results = new Map(messages.filter(m => m.role === "tool").map(m => [m.tool_call_id, m.content ?? ""]));
  for (const m of messages) {
    if (m.role === "user") out.push({ id: `m-${m.id}`, role: "user", text: m.content ?? "", tools: [] });
    else if (m.role === "assistant" && m.tool_calls?.length) pending.push(...m.tool_calls.map(c => ({ id: c.id, name: c.name, arguments: c.arguments, result: results.get(c.id) ?? "" })));
    else if (m.role === "assistant") { out.push({ id: `m-${m.id}`, role: "assistant", text: m.content ?? "", tools: pending }); pending = []; }
  }
  return out;
}
