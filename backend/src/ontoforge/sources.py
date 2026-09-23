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
from urllib.parse import quote
from uuid import UUID

from ontoforge.build import DatabricksSource, PostgresSource, SourceEngine, databricks_connect_factory
from ontoforge.config import Settings
from ontoforge.db import Database
from ontoforge.registry import Domain, Registry


# What each connector usually calls a field, in the order to try. The hub's own schema decides
# when it can be read; this is the fallback for a hub that cannot answer, and the vocabulary for
# matching what it does say.
_ALIASES = {"host": ("host", "hostname", "server"), "port": ("port",), "database": ("database", "dbname", "db"),
            "user": ("username", "user", "login"), "sslmode": ("sslmode", "ssl_mode")}


def postgres_url(cred: dict, spec: dict | None) -> str:
    """The DSN for a Postgres connection, built from the field names its connector declares.

    Guessing here is how a connection with a renamed or missing field quietly becomes a
    connection to the app's own database: a missing host used to default to localhost. The
    connector's own schema names the fields, including which one holds the secret, and anything
    it marks required and does not carry is refused by name.
    """
    cfg = dict(cred.get("config") or {})
    name = cred.get("name") or cred.get("id") or "the connection"
    declared = {f["name"] for f in (spec or {}).get("fields", [])}
    secret_field = (spec or {}).get("secret_field") or ""

    def pick(role: str) -> str | None:
        names = [n for n in _ALIASES[role] if not declared or n in declared] or list(_ALIASES[role])
        return next((str(cfg[n]) for n in names if cfg.get(n) not in (None, "")), None)

    host, database, user = pick("host"), pick("database"), pick("user")
    password = str(cfg.get(secret_field) or cfg.get("password") or "")
    missing = [role for role, value in (("host", host), ("database", database)) if not value]
    required = {f["name"] for f in (spec or {}).get("fields", []) if f.get("required")}
    missing += [f for f in sorted(required) if cfg.get(f) in (None, "") and f not in (secret_field, *(_ALIASES["host"] + _ALIASES["database"]))]
    if missing:
        raise ValueError(f"Connection {name!r} is missing {', '.join(dict.fromkeys(missing))}: "
                         "fill it in the connection module before this source can be read.")

    port = pick("port") or "5432"
    url = f"postgresql://{quote(user or '', safe='')}:{quote(password, safe='')}@{host}:{port}/{database}"
    sslmode = pick("sslmode")
    return f"{url}?sslmode={sslmode}" if sslmode else url


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
            engine = self._open(self.connections.credentials(connection_id), catalog, schema, self._spec(c.get("kind")))
            self._cache = {k: e for k, e in self._cache.items() if k[0] != connection_id}   # one engine per connection
            self._cache[key] = engine
        return engine

    def _spec(self, kind: str | None) -> dict | None:
        """What the connection module says this connector's fields are called. None when it cannot say."""
        if not kind:
            return None
        try:
            return self.connections.spec(kind)
        except Exception:  # noqa: BLE001 - the documented names are the fallback, not a failure
            return None

    @staticmethod
    def _open(cred: dict, catalog: str | None, schema: str | None, spec: dict | None = None) -> SourceEngine:
        kind, cfg, name = cred["kind"], cred["config"], cred.get("name") or cred["id"]
        if kind == "databricks":
            if (cfg.get("auth_type") or "pat") != "pat" or not cfg.get("token"):
                raise ValueError(f"Connection {name}: only Databricks connections with a personal access token can be opened for builds yet")
            host = str(cfg.get("host") or "").replace("https://", "").rstrip("/")
            cat = catalog or cfg.get("catalog") or None
            connect = databricks_connect_factory(host, str(cfg.get("http_path") or ""), str(cfg["token"]), cat, schema)
            return DatabricksSource(connect, cat, schema)
        if kind == "postgres":
            return PostgresSource(Database(postgres_url(cred, spec), schema=schema), schema)
        raise ValueError(f"Connection {name} is a {kind} connection; datagraph can read Databricks and Postgres sources")
