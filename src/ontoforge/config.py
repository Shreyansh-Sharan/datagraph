"""Runtime settings. Every value can be overridden with an ``ONTOFORGE_``-prefixed env var."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ONTOFORGE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://ontoforge:ontoforge@localhost:5439/ontoforge"
    database_schema: str | None = None
    base_iri: str = "http://ontoforge.local/"
    build_workers: int = 2
    log_format: str = "text"            # "text" | "json"
    log_level: str = "INFO"

    auth_mode: str = "header"           # "header" (trusted proxy / dev) | "token" (API keys)
    auth_header: str = "X-Actor"        # identity header in header mode (Databricks Apps: X-Forwarded-Email)
    auth_default_role: str = "viewer"   # role for principals without an explicit one
    source_kind: str = "postgres"       # "postgres" (registry database) | "databricks"
    databricks_host: str | None = None
    databricks_http_path: str | None = None
    databricks_token: str | None = None
    databricks_catalog: str | None = None
    databricks_schema: str | None = None

    llm_provider: str = "none"          # "none" | "anthropic"
    llm_model: str = "claude-opus-5"


def load_settings() -> Settings:
    return Settings()
