"""The assistant: a model that answers questions about a domain by calling the MCP tools, acts as
the caller where a tool acts, and keeps every thread with the tool calls it made.

The model never reaches the database or the warehouse: it only sees the MCP tool catalogue and
receives what those tools return, under the caller's identity and the domain's MCP policy."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Callable
from uuid import UUID

from psycopg.types.json import Jsonb

from ontoforge.db import Database
from ontoforge.llm.provider import LLMProvider, LLMUnavailable
from ontoforge.mcp.tools import ACTOR, ROLE
from ontoforge.notifications import VIA
from ontoforge.registry.models import NotFound

SYSTEM = """\
You are the assistant of datagraph, a tool where data engineers design an ontology over warehouse
tables, map it, profile tables, define data-quality rules, keep a glossary and build a knowledge
graph. Answer the user's question with the tools; never guess what a tool can tell you. Prefer one
well-chosen tool call over many. When you act (start a build, profile a table, run or add rules),
say what you did and what to look at next. Keep answers short and concrete: names, numbers, next
step. If a tool reports an error, say so plainly and suggest what would fix it. When something is
outside the tools' reach, say you cannot see it rather than inventing it. Name tables exactly as
list_tables or the context spells them; never correct a table name from memory.

Prefer the graph over the warehouse: the knowledge graph carries the business meaning (classes,
relationships, labels), so answer from it with search_entities, describe_entity, class_schema,
ontology_paths and graph_aggregate; use preview_sql only for data the graph does not hold.

When asked why something is the case (a trend, an inconsistency, an outlier, a gap), work like an
analyst: 1) find the subject with search_entities and take its class from the types it returns;
2) learn what connects to it with class_schema (its incoming relationships name the classes that
carry its events) and ontology_paths; 3) measure it with graph_aggregate, over time (group_kind
year or month, filtered to the subject) and against its peers (group by the relationship), one
dimension at a time, then break the odd period or peer down by the next relationship (products,
customers, people); 4) before calling a last period a decline or a peer an outlier, check the data
behind it: the source table's date range and freshness from table_profile and its rule results from
table_quality, because a partial period or a failing rule explains many "inconsistencies"; 5) answer
with the finding, the numbers behind it, the likely cause, and what you could not see. Measure the
class that carries the events (orders, transactions, records) linked to the subject, not the
subject's own summary attributes. When the events class carries no date of its own, group by a path
through its incoming relationship to the class that has one: group_by ['^salesOrderHasDetailLine',
'salesOrderDate'] with group_kind year walks from the line to its order ('^' walks a relationship
backwards) and takes the order's date; never call that impossible. When the user does not say what is inconsistent, do not ask: run
the usual checks, the last period against the earlier ones, the subject against its peers, and the
rule results, and report what stands out. Use the class names exactly as the tools return them;
never guess a class name. Do not start profiles, rule runs or builds while answering a question;
only act when the user asks you to act. Answer as soon as the numbers answer the question: at most
eight tool calls for a why.

You can change the design of the working draft, not only read it: add_class, map_class,
add_attribute, add_relationship (with fk_column and fk_on, or link_table with its keys),
map_relationship, remove_relationship, then start_build to load the change. When a question needs
a path the ontology lacks but the tables carry (a foreign-key column such as ProductModelID on a
link table, visible in table_profile, list_tables or preview_sql), say which relationship is
missing and offer to add it; when the user asks you to create it, add it with its key, start the
build, and say to ask again once list_builds shows it finished. Never say you cannot change the
ontology or the mapping. The rest of the backend is yours too: glossary terms and metrics
(add_term, update_term, delete_term), the version lifecycle (create_version, transition_version,
review_version, comment_version, set_active_version), domain settings and MCP policy, table
snapshots (import_tables, refresh_metadata, set_table_comment, remove_table), mapping exclusions,
reasoning rules (add_rule) and graph constraints (add_constraint). Reviewer and admin actions
need that role; a tool tells you when the caller lacks it. Never aggregate along a path ontology_paths did not return: when it
returns no path, the answer is that the relationship is missing, which table carries it (the link
class's table and keys from class_schema and list_tables), and the offer to add it.

Write answers in Markdown: short paragraphs, bullet lists, a table for a comparison, bold only the
finding. When an answer carries a series (over time, across peers), add a chart after the text as a
fenced code block whose language is chart, holding JSON like
{"type": "line", "title": "Southwest sales by year", "unit": "USD", "series": [{"name": "Total due",
"points": [{"x": "2022", "y": 3710548.6}, {"x": "2023", "y": 8763318.8}]}]}
Use line for time and bar for peers, at most three series, and keep the key numbers in the text.
"""
RESULT_LIMIT = 6000      # characters of a tool result the model gets to read
PREVIEW_LIMIT = 1200     # characters of a tool result the screen shows
Event = Callable[[dict], Any]


class Assistant:
    def __init__(self, server, llm: LLMProvider | None, db: Database, max_steps: int = 10) -> None:
        self.server, self.llm, self.db, self.max_steps = server, llm, db, max_steps

    # -- the conversation loop ------------------------------------------------------------------------

    async def chat(self, *, actor: str, message: str, context: dict | None = None, conversation_id: UUID | None = None,
                   on_event: Event | None = None, role: str | None = None) -> dict:
        if self.llm is None:
            raise LLMUnavailable("No LLM provider configured")
        emit = on_event or (lambda _e: None)
        context = context or {}
        conv_id = self._conversation(conversation_id, actor, message, context)
        history = self._messages(conv_id)
        self._save(conv_id, "user", message)
        msgs = history + [{"role": "user", "content": message}]
        tools = [{"name": t.name, "description": t.description or "", "input_schema": t.input_schema} for t in await self.server.list_tools()]
        system = SYSTEM + _context_lines(context)
        trace: list[dict] = []
        token, rtoken, vtoken = ACTOR.set(actor), ROLE.set(role), VIA.set("assistant")
        try:
            for _ in range(self.max_steps):
                reply = await asyncio.to_thread(self.llm.chat, system, msgs, tools)
                if not reply.tool_calls:
                    answer = reply.text.strip() or "I have nothing to add."
                    emit({"type": "text", "text": answer})
                    self._save(conv_id, "assistant", answer)
                    self._touch(conv_id)
                    return {"conversation_id": str(conv_id), "answer": answer, "tools": trace}
                calls = [{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in reply.tool_calls]
                msgs.append({"role": "assistant", "content": reply.text, "tool_calls": calls})
                self._save(conv_id, "assistant", reply.text, tool_calls=calls)
                for tc in reply.tool_calls:
                    emit({"type": "tool_call", "id": tc.id, "name": tc.name, "arguments": tc.arguments})
                    result = await self._call(tc.name, tc.arguments)
                    emit({"type": "tool_result", "id": tc.id, "name": tc.name, "result": result[:PREVIEW_LIMIT]})
                    trace.append({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "result": result[:PREVIEW_LIMIT]})
                    msgs.append({"role": "tool", "tool_call_id": tc.id, "name": tc.name, "content": result[:RESULT_LIMIT]})
                    self._save(conv_id, "tool", result[:RESULT_LIMIT], tool_call_id=tc.id, name=tc.name)
            # The budget is spent: one closing turn without tools, answered from what was gathered.
            nudge = "Answer now from what you have gathered, in a few sentences: the finding, the numbers behind it, and what you could not check."
            closing = await asyncio.to_thread(self.llm.chat, system, msgs + [{"role": "user", "content": nudge}], [])
            answer = closing.text.strip() or "I ran out of steps before reaching an answer; try a narrower question."
            emit({"type": "text", "text": answer})
            self._save(conv_id, "assistant", answer)
            self._touch(conv_id)
            return {"conversation_id": str(conv_id), "answer": answer, "tools": trace}
        finally:
            ACTOR.reset(token)
            ROLE.reset(rtoken)
            VIA.reset(vtoken)

    async def _call(self, name: str, arguments: dict) -> str:
        """One MCP tool call, its result as text; an error becomes text too so the model can recover."""
        try:
            res = await self.server.call_tool(name, arguments)
        except Exception as exc:  # noqa: BLE001 - the model reads the failure and decides
            cause = exc
            while getattr(cause, "__cause__", None) is not None:   # the SDK wraps a tool's exception: the reason is inside
                cause = cause.__cause__
            return f"Error: {type(cause).__name__}: {cause}"
        structured = getattr(res, "structured_content", None)
        if structured is not None:
            body = structured.get("result", structured) if isinstance(structured, dict) else structured
            return json.dumps(body, default=str)
        parts = [getattr(c, "text", None) for c in (getattr(res, "content", None) or [])]
        return "\n".join(p for p in parts if p) or "(no result)"

    # -- threads ------------------------------------------------------------------------------------

    def conversations(self, actor: str, domain: str | None = None) -> list[dict]:
        with self.db.rows() as cur:
            rows = cur.execute("SELECT id, domain, title, context, created_at, updated_at FROM conversations WHERE actor = %s AND (%s::text IS NULL OR domain = %s) "
                               "ORDER BY updated_at DESC LIMIT 100", (actor, domain, domain)).fetchall()
        return [_conv(r) for r in rows]

    def conversation(self, conversation_id: UUID, actor: str | None = None) -> dict:
        with self.db.rows() as cur:
            conv = cur.execute("SELECT * FROM conversations WHERE id = %s", (conversation_id,)).fetchone()
            if not conv or (actor is not None and conv["actor"] != actor):
                raise NotFound(f"Conversation {conversation_id}")
            msgs = cur.execute("SELECT id, role, content, tool_calls, tool_call_id, name, created_at FROM messages WHERE conversation_id = %s ORDER BY id", (conversation_id,)).fetchall()
        return {**_conv(conv), "messages": [{"id": m["id"], "role": m["role"], "content": m["content"], "tool_calls": m["tool_calls"], "tool_call_id": m["tool_call_id"],
                                             "name": m["name"], "created_at": m["created_at"].isoformat()} for m in msgs]}

    def delete(self, conversation_id: UUID, actor: str) -> None:
        with self.db.rows() as cur:
            gone = cur.execute("DELETE FROM conversations WHERE id = %s AND actor = %s RETURNING id", (conversation_id, actor)).fetchone()
        if not gone:
            raise NotFound(f"Conversation {conversation_id}")

    def _conversation(self, conversation_id: UUID | None, actor: str, message: str, context: dict) -> UUID:
        with self.db.rows() as cur:
            if conversation_id is not None:
                row = cur.execute("SELECT id FROM conversations WHERE id = %s AND actor = %s", (conversation_id, actor)).fetchone()
                if not row:
                    raise NotFound(f"Conversation {conversation_id}")
                return row["id"]
            title = message.strip().splitlines()[0][:80] if message.strip() else "New conversation"
            return cur.execute("INSERT INTO conversations (actor, domain, title, context) VALUES (%s, %s, %s, %s) RETURNING id",
                               (actor, context.get("domain"), title, Jsonb(context))).fetchone()["id"]

    def _messages(self, conversation_id: UUID) -> list[dict]:
        with self.db.rows() as cur:
            rows = cur.execute("SELECT role, content, tool_calls, tool_call_id, name FROM messages WHERE conversation_id = %s ORDER BY id", (conversation_id,)).fetchall()
        out = []
        for r in rows:
            m: dict = {"role": r["role"], "content": r["content"] or ""}
            if r["tool_calls"]:
                m["tool_calls"] = r["tool_calls"]
            if r["role"] == "tool":
                m["tool_call_id"], m["name"] = r["tool_call_id"], r["name"]
            out.append(m)
        return out

    def _save(self, conversation_id: UUID, role: str, content: str | None, *, tool_calls: list | None = None, tool_call_id: str | None = None, name: str | None = None) -> None:
        with self.db.rows() as cur:
            cur.execute("INSERT INTO messages (conversation_id, role, content, tool_calls, tool_call_id, name) VALUES (%s, %s, %s, %s, %s, %s)",
                        (conversation_id, role, content, Jsonb(tool_calls) if tool_calls else None, tool_call_id, name))

    def _touch(self, conversation_id: UUID) -> None:
        with self.db.rows() as cur:
            cur.execute("UPDATE conversations SET updated_at = now() WHERE id = %s", (conversation_id,))


def _context_lines(context: dict) -> str:
    known = [(k, context[k]) for k in ("domain", "version", "screen", "table", "entity", "cls") if context.get(k)]
    if not known:
        return "\nThe user is at the home screen with no domain selected: ask, or call list_domains."
    return "\nWhere the user is right now (pass the domain to tools unless they ask about another): " + ", ".join(f"{k} = {v}" for k, v in known) + "."


def _conv(r: dict) -> dict:
    return {"id": str(r["id"]), "domain": r["domain"], "title": r["title"], "context": r["context"] or {},
            "created_at": r["created_at"].isoformat(), "updated_at": r["updated_at"].isoformat()}
