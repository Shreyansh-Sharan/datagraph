# ADR 0004 — LLM access goes through a port; model output is validated before it is accepted

**Status:** accepted · **Date:** 2026-09-20

## Decision
Every LLM feature (draft ontology, suggest mapping, natural-language ontology edits) calls a
single interface, `LLMProvider.complete_json(system, user, schema)`, and receives a dict shaped
by a JSON schema. The Anthropic implementation uses the Messages API's structured outputs
(`output_config.format`), adaptive thinking, streaming, and server-side refusal fallbacks.
A `FakeProvider` with canned answers serves the test-suite. Task code never sees a vendor SDK.

Model answers are treated as untrusted input: class/property names must resolve to the ontology,
table/column names must exist in the catalog, and a suggested mapping must compile to R2RML,
or the task raises `LLMOutputError` (HTTP 502) instead of storing anything.

## Sources
- Anthropic Messages API structured outputs and adaptive thinking (Claude API docs, 2026)
- Same ports-and-adapters rationale as ADR 0002

## Why
- Customers have their own model contracts; the provider must be swappable.
- Prompts are the most copyright-sensitive and most quality-sensitive asset: keeping them in one
  reviewable module (`llm/prompts.py`) makes them ours, versioned, and cacheable.
- Validation turns "the model hallucinated a column" into a 502 with a message rather than a
  broken build.

## Consequences
- Prompt caching works because system prompts are constants and volatile content comes last.
- An eval harness for the three tasks is the natural next step (prompts are testable in isolation).
