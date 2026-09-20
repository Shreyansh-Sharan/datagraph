"""Runtime settings. Every value can be overridden with an ``ONTOFORGE_``-prefixed env var."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ONTOFORGE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://ontoforge:ontoforge@localhost:5439/ontoforge"
    database_schema: str | None = None
    base_iri: str = "http://ontoforge.local/"


def load_settings() -> Settings:
    return Settings()
