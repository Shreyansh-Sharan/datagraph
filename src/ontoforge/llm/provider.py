"""The LLM port: ask for JSON that matches a schema, get a dict back.

``AnthropicProvider`` is the first implementation; ``FakeProvider`` serves tests. Nothing above
this module knows which vendor is answering.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass


class LLMOutputError(ValueError):
    """The model's answer was well-formed JSON but semantically unusable (or it refused)."""


class LLMUnavailable(RuntimeError):
    """No LLM provider is configured."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ChatReply:
    text: str
    tool_calls: list[ToolCall]
    stop: str = "end"        # end | tool_calls | length


class LLMProvider(ABC):
    @abstractmethod
    def complete_json(self, system: str, user: str, schema: dict) -> dict: ...

    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> ChatReply:
        """One turn of a tool-using conversation. ``messages`` are neutral: user / assistant (with
        ``tool_calls``) / tool (with ``tool_call_id`` and ``name``); ``tools`` carry name, description
        and input_schema. Providers translate to their own wire format."""
        raise LLMUnavailable(f"{type(self).__name__} cannot hold a conversation")


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


class AnthropicProvider(LLMProvider):
    """Claude via the official SDK, using structured outputs (``output_config.format``).

    Streams (long outputs), adaptive thinking, and - by default - server-side refusal
    fallbacks so a policy decline on the primary model is retried on a fallback in the
    same call. Pass ``fallbacks=False`` to disable.
    """

    def __init__(self, client=None, model: str = "claude-opus-5", max_tokens: int = 32000,
                 effort: str = "high", fallbacks: bool = True) -> None:
        if client is None:
            import anthropic  # lazy: optional at import time
            client = anthropic.Anthropic()
        self.client, self.model, self.max_tokens, self.effort, self.fallbacks = client, model, max_tokens, effort, fallbacks

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        kwargs = dict(
            model=self.model, max_tokens=self.max_tokens, system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": user}],
        )
        if self.fallbacks:
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"
        with self.client.beta.messages.stream(**kwargs) as stream:
            message = stream.get_final_message()
        if message.stop_reason == "refusal":
            raise LLMOutputError("The model declined this request")
        if message.stop_reason == "max_tokens":
            raise LLMOutputError("The model's answer was cut off (max_tokens); raise max_tokens or narrow the input")
        text = next((b.text for b in message.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMOutputError(f"Model returned invalid JSON: {exc}") from None


    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> ChatReply:
        content: list[dict] = []
        for m in messages:
            if m["role"] == "user":
                content.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                blocks = ([{"type": "text", "text": m["content"]}] if m.get("content") else []) + \
                         [{"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["arguments"]} for tc in m.get("tool_calls") or []]
                content.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
            elif m["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                if content and content[-1]["role"] == "user" and isinstance(content[-1]["content"], list):
                    content[-1]["content"].append(block)
                else:
                    content.append({"role": "user", "content": [block]})
        spec = [{"name": t["name"], "description": t.get("description") or "", "input_schema": t["input_schema"]} for t in tools]
        message = self.client.messages.create(model=self.model, max_tokens=min(self.max_tokens, 8000), system=system, messages=content, tools=spec)
        text = "".join(b.text for b in message.content if b.type == "text")
        calls = [ToolCall(b.id, b.name, dict(b.input or {})) for b in message.content if b.type == "tool_use"]
        return ChatReply(text, calls, "tool_calls" if calls else ("length" if message.stop_reason == "max_tokens" else "end"))


class AzureOpenAIProvider(LLMProvider):
    """An Azure OpenAI chat deployment (e.g. GPT-5.1) with strict JSON-schema output."""

    def __init__(self, client=None, deployment: str = "gpt-5.1", *, api_key: str | None = None,
                 endpoint: str | None = None, api_version: str | None = None, max_tokens: int = 16000, timeout: float = 180) -> None:
        if client is None:
            from openai import AzureOpenAI  # lazy: optional dependency
            # Bounded: the SDK's defaults (10 minutes per attempt, two retries) turn a hung request into a half-hour job.
            client = AzureOpenAI(api_key=api_key, azure_endpoint=endpoint, api_version=api_version, timeout=timeout, max_retries=1)
        self.client, self.deployment, self.max_tokens = client, deployment, max_tokens

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        response = self.client.chat.completions.create(
            model=self.deployment,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_schema", "json_schema": {"name": "ontoforge_output", "schema": schema, "strict": True}},
            max_completion_tokens=self.max_tokens,
        )
        choice = response.choices[0]
        message = choice.message
        if getattr(message, "refusal", None):
            raise LLMOutputError(f"The model declined this request: {message.refusal}")
        if choice.finish_reason == "length":
            raise LLMOutputError("The model's answer was cut off (max tokens); narrow the input")
        try:
            return json.loads(message.content or "")
        except json.JSONDecodeError as exc:
            raise LLMOutputError(f"Model returned invalid JSON: {exc}") from None


    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> ChatReply:
        wire: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "assistant":
                entry: dict = {"role": "assistant", "content": m.get("content") or None}
                if m.get("tool_calls"):
                    entry["tool_calls"] = [{"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])}} for tc in m["tool_calls"]]
                wire.append(entry)
            elif m["role"] == "tool":
                wire.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
            else:
                wire.append({"role": "user", "content": m["content"]})
        spec = [{"type": "function", "function": {"name": t["name"], "description": t.get("description") or "", "parameters": t["input_schema"]}} for t in tools]
        response = self.client.chat.completions.create(model=self.deployment, messages=wire, tools=spec or None, max_completion_tokens=min(self.max_tokens, 8000))
        choice = response.choices[0]
        calls = []
        for tc in choice.message.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(tc.id, tc.function.name, args))
        return ChatReply(choice.message.content or "", calls, "tool_calls" if calls else ("length" if choice.finish_reason == "length" else "end"))
