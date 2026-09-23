"""Which source a domain reads: its own connection from the connection module, or the deployment's.

Every domain source (see ``Domain.sources``) names a hub connection. The hub keeps the
credentials; with a service token we fetch them once and open the warehouse ourselves, which is
what catalog browsing, previews, metadata snapshots and builds need. A domain without a
connection reads the deployment's own source, but only where there is no connection module to
point at: with one configured, an unattached domain is a misconfiguration and says so instead of
quietly mapping the registry database and looking like it worked.
"""
from __future__ import annotations

from typing import Callable
from uuid import UUID

from ontoforge.build import DatabricksSource, PostgresSource, SourceEngine, databricks_connect_factory
from ontoforge.config import Settings
from ontoforge.db import Database
from ontoforge.registry import Domain, Registry


class SourceResolver:
    def __init__(self, settings: Settings, registry: Registry, connections, env_factory: Callable[[], SourceEngine]) -> None:
        self.settings, self.registry, self.connections = settings, registry, connections
        self._env_factory = env_factory
        self._env: SourceEngine | None = None
        self._cache: dict[tuple, SourceEngine] = {}

    # -- the deployment's own source ------------------------------------------------------
    @property
    def env(self) -> SourceEngine:
        if self._env is None:
            self._env = self._env_factory()
        return self._env

    # -- per domain ------------------------------------------------------------------------
    def for_domain(self, domain: Domain | str) -> SourceEngine:
        d = self.registry.get_domain(domain) if isinstance(domain, str) else domain
        primary = d.primary
        if not primary.get("connection_id"):
            if getattr(self.connections, "source", "none") != "none":
                raise ValueError(f"Domain {d.name!r} has no source connection: pick one in Configure. "
                                 "Until then nothing can read its tables.")
            return self.env                              # no connection module: the deployment is the source
        return self.for_connection(primary["connection_id"], catalog=primary.get("catalog"), schema=d.default_schema)

    def for_version(self, version_id: UUID) -> SourceEngine:
        v = self.registry.get_version(version_id)
        return self.for_domain(self.registry.get_domain_by_id(v.domain_id))

    def catalog_for(self, version_id: UUID):
        return self.for_version(version_id).catalog

    def for_connection(self, connection_id: str, *, catalog: str | None = None, schema: str | None = None) -> SourceEngine:
        c = self.connections.get(connection_id)          # NotFound / HubUnavailable surface as themselves
        key = (connection_id, c.get("updated_at"), catalog, schema)
        engine = self._cache.get(key)
        if engine is None:
            engine = self._open(self.connections.credentials(connection_id), catalog, schema)
            self._cache = {k: e for k, e in self._cache.items() if k[0] != connection_id}   # one engine per connection
            self._cache[key] = engine
        return engine

    @staticmethod
    def _open(cred: dict, catalog: str | None, schema: str | None) -> SourceEngine:
        kind, cfg, name = cred["kind"], cred["config"], cred.get("name") or cred["id"]
        if kind == "databricks":
            if (cfg.get("auth_type") or "pat") != "pat" or not cfg.get("token"):
                raise ValueError(f"Connection {name}: only Databricks connections with a personal access token can be opened for builds yet")
            host = str(cfg.get("host") or "").replace("https://", "").rstrip("/")
            cat = catalog or cfg.get("catalog") or None
            connect = databricks_connect_factory(host, str(cfg.get("http_path") or ""), str(cfg["token"]), cat, schema)
            return DatabricksSource(connect, cat, schema)
        if kind == "postgres":
            user, pw = cfg.get("username") or cfg.get("user") or "", cfg.get("password") or ""
            url = f"postgresql://{user}:{pw}@{cfg.get('host', 'localhost')}:{cfg.get('port', 5432)}/{cfg.get('database', '')}"
            if cfg.get("sslmode"):
                url += f"?sslmode={cfg['sslmode']}"
            return PostgresSource(Database(url, schema=schema), schema)
        raise ValueError(f"Connection {name} is a {kind} connection; datagraph can read Databricks and Postgres sources")
