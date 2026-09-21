from __future__ import annotations

import httpx

from .base import Connector, ConnectorSpec, Field, TestResult


class AzureOpenAIConnector(Connector):
    spec = ConnectorSpec(
        kind="azure_openai", label="Azure OpenAI", category="ai", secret_field="api_key",
        fields=(
            Field("endpoint", "Endpoint", help="https://<resource>.openai.azure.com"),
            Field("api_key", "API key", kind="password", required=False),
            Field("deployment", "Deployment", help="Chat deployment name, e.g. gpt-5.1"),
            Field("api_version", "API version", required=False, default="2024-08-01-preview"),
        ),
        docs="https://learn.microsoft.com/azure/ai-services/openai/reference",
    )

    def _probe(self, config: dict, secret: str | None) -> TestResult:
        base = config["endpoint"].rstrip("/")
        version = config.get("api_version") or "2024-08-01-preview"
        with httpx.Client(timeout=8.0) as http:
            r = http.get(f"{base}/openai/models", params={"api-version": version}, headers={"api-key": secret or ""})
            if r.status_code != 200:
                body = r.text[:300]
                raise RuntimeError(f"HTTP {r.status_code} from {base}/openai/models: {body}")
            models = [m.get("id") for m in r.json().get("data", [])]
        deployment = config["deployment"]
        detail = f"{len(models)} models available · deployment {deployment}"
        return TestResult(True, "Connected", detail, facts={"models": len(models), "deployment": deployment})

    def advice(self, message: str) -> str | None:
        if "401" in message or "403" in message:
            return "The API key is not valid for this resource; copy it from Keys and Endpoint in the Azure portal."
        if "404" in message:
            return "Check the endpoint: it must be the resource URL, https://<resource>.openai.azure.com."
        if "Connect" in message or "timed out" in message.lower():
            return "The endpoint is unreachable from this deployment; check the URL and private-endpoint rules."
        return None
