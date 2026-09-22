"""The LLM port: ask for JSON that matches a schema, get a dict back.

``AnthropicProvider`` is the first implementation; ``FakeProvider`` serves tests. Nothing above
this module knows which vendor is answering.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod


class LLMOutputError(ValueError):
    """The model's answer was well-formed JSON but semantically unusable (or it refused)."""


class LLMUnavailable(RuntimeError):
    """No LLM provider is configured."""


class LLMProvider(ABC):
    @abstractmethod
    def complete_json(self, system: str, user: str, schema: dict) -> dict: ...


class FakeProvider(LLMProvider):
    """Returns canned responses in order and records every call."""

    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []

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
