"""Connection adapters: one per warehouse or AI provider, each with a field schema the UI renders
and a ``test`` that reports success or the provider's error verbatim.

Postgres and Databricks are the primary source adapters; SQL Server is the next warehouse;
Azure OpenAI is the AI adapter.
"""
from .base import Connector, ConnectorSpec, Field, TestResult
from .postgres import PostgresConnector
from .databricks import DatabricksConnector
from .sqlserver import SqlServerConnector
from .azure_openai import AzureOpenAIConnector

CONNECTORS: dict[str, Connector] = {c.spec.kind: c for c in (PostgresConnector(), DatabricksConnector(), SqlServerConnector(), AzureOpenAIConnector())}


def specs() -> list[dict]:
    return [c.spec.to_dict() for c in CONNECTORS.values()]


def connector(kind: str) -> Connector:
    try:
        return CONNECTORS[kind]
    except KeyError:
        raise ValueError(f"Unknown connection kind {kind!r}; choose from {', '.join(CONNECTORS)}") from None


__all__ = ["CONNECTORS", "Connector", "ConnectorSpec", "Field", "TestResult", "connector", "specs"]
