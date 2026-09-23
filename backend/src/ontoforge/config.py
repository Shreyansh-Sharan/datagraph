"""Runtime settings. Every value can be overridden with an ``ONTOFORGE_``-prefixed env var."""
from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ONTOFORGE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://ontoforge:ontoforge@localhost:5439/ontoforge"
    database_schema: str | None = None
    base_iri: str = "http://ontoforge.local/"
    build_workers: int = 2
    ui_dir: str | None = None           # a built frontend/ to serve at /ui; unset means the API serves no interface
    log_format: str = "text"            # "text" | "json"
    log_level: str = "INFO"

    connections_hub_url: str | None = None        # Polestar connection module (mf-studio-connectors hub); connections live there
    connections_hub_token: str | None = None
    connections_hub_service_token: str | None = None   # one of the hub's CM_SERVICE_TOKENS: lets builds open a domain's connection      # bearer token for the hub (platform user token), optional
    auth_mode: str = "header"           # "header" (trusted proxy / dev) | "token" (API keys)
    auth_header: str = "X-Actor"        # identity header in header mode (Databricks Apps: X-Forwarded-Email)
    auth_default_role: str = "viewer"   # role for principals without an explicit one
    source_kind: str = "postgres"       # "postgres" (registry database) | "databricks"
    databricks_host: str | None = None
    databricks_http_path: str | None = None
    databricks_token: str | None = None
    databricks_catalog: str | None = None
    databricks_schema: str | None = None

    warehouse_target_schema: str | None = None   # where to publish triple views/tables (e.g. "main.kg")
    warehouse_materialization: str = "none"      # "none" | "view" | "table"

    llm_provider: str = "none"          # "none" | "anthropic" | "azure_openai"
    llm_model: str = "claude-opus-5"
    azure_openai_api_key: str | None = Field(default=None, validation_alias=AliasChoices("AZURE_OPENAI_API_KEY", "ONTOFORGE_AZURE_OPENAI_API_KEY"))
    azure_openai_endpoint: str | None = Field(default=None, validation_alias=AliasChoices("AZURE_OPENAI_ENDPOINT", "ONTOFORGE_AZURE_OPENAI_ENDPOINT"))
    azure_openai_deployment: str = Field(default="gpt-5.1", validation_alias=AliasChoices("AZURE_OPENAI_DEPLOYMENT", "ONTOFORGE_AZURE_OPENAI_DEPLOYMENT"))
    azure_openai_api_version: str = Field(default="2024-08-01-preview", validation_alias=AliasChoices("AZURE_OPENAI_API_VERSION", "ONTOFORGE_AZURE_OPENAI_API_VERSION"))


def load_settings() -> Settings:
    return Settings()
