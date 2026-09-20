"""Azure OpenAI as a second LLMProvider implementation (structured JSON output)."""
import json

from ontoforge.llm import AzureOpenAIProvider, LLMOutputError


class StubCompletions:
    def __init__(self, payload):
        self.payload, self.kwargs = payload, None

    def create(self, **kwargs):
        self.kwargs = kwargs

        class Msg:
            content = json.dumps(self.payload)
            refusal = None

        class Choice:
            message = Msg()
            finish_reason = "stop"

        class Resp:
            choices = [Choice()]

        return Resp()


class StubClient:
    def __init__(self, payload):
        self.chat = type("Chat", (), {})()
        self.chat.completions = StubCompletions(payload)


def test_azure_provider_requests_json_schema_output():
    client = StubClient({"ok": True})
    p = AzureOpenAIProvider(client=client, deployment="gpt-5.1")
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
    assert p.complete_json("sys", "user", schema) == {"ok": True}
    kw = client.chat.completions.kwargs
    assert kw["model"] == "gpt-5.1"
    assert kw["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "user"}]
    assert kw["response_format"]["type"] == "json_schema" and kw["response_format"]["json_schema"]["schema"] == schema
    assert kw["response_format"]["json_schema"]["strict"] is True


def test_azure_provider_reports_refusals():
    client = StubClient({})
    client.chat.completions.create = lambda **kw: type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": None, "refusal": "no"})(), "finish_reason": "stop"})()]})()
    try:
        AzureOpenAIProvider(client=client, deployment="d").complete_json("s", "u", {"type": "object"})
    except LLMOutputError as e:
        assert "declined" in str(e)
    else:
        raise AssertionError("expected LLMOutputError")
