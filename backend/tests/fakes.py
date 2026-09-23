"""Test doubles. They live here, not in the shipped package, so nothing can reach them by import."""
from __future__ import annotations

from ontoforge.llm import ChatReply, LLMOutputError, LLMProvider, ToolCall


class FakeProvider(LLMProvider):
    """Scripted answers for tests: ``responses`` feed complete_json, ``turns`` feed chat."""
    """Returns canned responses in order and records every call."""

    def __init__(self, responses: list[dict], turns: list[dict] | None = None) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []
        self.turns, self.calls, self._n = list(turns or []), [], 0

    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> ChatReply:
        self.calls.append({"system": system, "messages": [dict(m) for m in messages], "tools": list(tools)})
        if not self.turns:
            raise LLMOutputError("FakeProvider has no scripted turn left")
        turn = self.turns.pop(0)
        calls = []
        for tc in turn.get("tool_calls", []):
            self._n += 1
            calls.append(ToolCall(tc.get("id") or f"call_{self._n}", tc["name"], dict(tc.get("arguments") or {})))
        return ChatReply(turn.get("text", ""), calls, "tool_calls" if calls else "end")

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        self.calls.append((system, user, schema))
        if not self.responses:
            raise LLMOutputError("FakeProvider has no responses left")
        return self.responses.pop(0)
