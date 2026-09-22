"""FastAPI application factory. All state hangs off ``app.state``; routes read it via ``deps``."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles


class _NoCacheStatic(StaticFiles):
    """ES modules are cached aggressively by browsers; force an ETag revalidation on every load."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response
from starlette.datastructures import Headers

from ontoforge.ui import STATIC_DIR

from ontoforge.analytics import AnalyticsError, GraphAnalytics
from ontoforge.attachments import AttachmentError, AttachmentService
from ontoforge.auth import AuthError, Forbidden, Principals
from ontoforge.cohorts import CohortEngine, CohortError
from ontoforge.auth.fastapi import principal_from_headers
from ontoforge.build import BuildPipeline, BuildScheduler, DatabricksSource, PublishConfig, PostgresSource, SourceEngine, databricks_connect_factory
from ontoforge.compiler import CompileError, IdentifierError
from ontoforge.config import Settings, load_settings
from ontoforge.db import Database, run_migrations
from ontoforge.llm import AnthropicProvider, AzureOpenAIProvider, LLMOutputError, LLMProvider, LLMUnavailable
from ontoforge.mapping import MappingSpecError
from ontoforge.assistant import Assistant
from ontoforge.mcp import GraphTools, create_mcp_server
from ontoforge.mcp.tools import ACTOR
from ontoforge.metadata import MetadataError, MetadataService
from ontoforge.profiling import ProfileService
from ontoforge.tabledq import TableQuality
from ontoforge.glossary import GlossaryService
from ontoforge.observability import RequestLoggingMiddleware, configure_logging
from ontoforge.r2rml import MappingError
from ontoforge.reasoning import Reasoner
from ontoforge.connectors import HubConnections, HubUnavailable, NoConnectionModule
from ontoforge.jobs import JobRunner
from ontoforge.sources import SourceResolver
from ontoforge.registry import LifecycleError, LockedError, NotFound, Registry
from ontoforge.quality import QualityError
from ontoforge.rules import RuleError
from ontoforge.store import TripleStore

from .routes import open_router, router

_STATUS = {HubUnavailable: 503, AuthError: 401, Forbidden: 403, NotFound: 404, LifecycleError: 409, LockedError: 423, LLMUnavailable: 503, LLMOutputError: 502,
           MetadataError: 409, RuleError: 400, QualityError: 400, AnalyticsError: 400, AttachmentError: 400, CohortError: 400, MappingSpecError: 400, MappingError: 400, CompileError: 400, IdentifierError: 400, ValueError: 400}


def create_app(db: Database, source_db: Database | None = None, settings: Settings | None = None,
               llm: LLMProvider | None = None, hub_client: "httpx.Client | None" = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_format, settings.log_level)
    app = FastAPI(title="ontoforge", version="0.1.0")
    app.add_middleware(RequestLoggingMiddleware, identity_header=settings.auth_header)
    app.state.settings = settings
    app.state.db = db
    app.state.registry = Registry(db)
    app.state.connections = _connections_backend(settings, hub_client)
    app.state.principals = Principals(db)
    app.state.store = TripleStore(db)
    app.state.graph_status_cache = {}   # version id -> ((build id, status, finished_at), status payload)
    app.state.sources = SourceResolver(settings, app.state.registry, app.state.connections, lambda: _source_engine(settings, source_db or db))
    publish = PublishConfig(settings.warehouse_target_schema, settings.warehouse_materialization) \
        if settings.warehouse_target_schema else None
    app.state.metadata = MetadataService(app.state.registry, app.state.sources.catalog_for, db)
    app.state.profiles = ProfileService(app.state.registry, app.state.metadata, app.state.sources.for_version, db)
    app.state.tabledq = TableQuality(app.state.registry, app.state.metadata, app.state.sources.for_version, db)
    app.state.glossary = GlossaryService(app.state.registry, db)
    app.state.pipeline = BuildPipeline(app.state.registry, app.state.store, app.state.sources.for_version, publish=publish,
                                       metadata=app.state.metadata)
    app.state.scheduler = BuildScheduler(app.state.pipeline, app.state.registry, workers=settings.build_workers)
    app.state.reasoner = Reasoner(app.state.registry, app.state.store)
    app.state.analytics = GraphAnalytics(app.state.registry, app.state.store)
    app.state.attachments = AttachmentService(app.state.registry, app.state.sources.for_version, app.state.store)
    app.state.cohorts = CohortEngine(app.state.registry, app.state.store)
    app.state.jobs = JobRunner(workers=settings.build_workers)
    app.state.llm = llm if llm is not None else _llm_provider(settings)   # the CLI's serve path passes none: build it from settings
    mcp_app = _mcp_mount(app)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.registry.fail_stale_builds()   # no worker survives a restart
        async with mcp_app.router.lifespan_context(mcp_app):   # mounted apps don't get their lifespan run for them
            yield
        app.state.scheduler.shutdown(wait=False)
        app.state.jobs.shutdown(wait=False)

    app.router.lifespan_context = lifespan
    app.include_router(open_router)
    app.include_router(router)
    app.mount("/ui", _NoCacheStatic(directory=STATIC_DIR, html=True), name="ui")   # public: the SPA authenticates via the API
    app.mount("/", _guarded(app, mcp_app))   # serves /mcp (Streamable HTTP); everything else 404s here

    for cls, code in _STATUS.items():
        app.add_exception_handler(cls, _handler(code))
    return app


def _mcp_mount(app: FastAPI):
    from mcp.server.transport_security import TransportSecuritySettings
    tools = GraphTools(app.state.registry, app.state.store, app.state.metadata, app.state.attachments, services=app.state)
    server = create_mcp_server(tools)
    app.state.mcp_server = server
    app.state.assistant = Assistant(server, app.state.llm, app.state.db)
    return server.streamable_http_app(streamable_http_path="/mcp", json_response=True, stateless_http=True,
                                      transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))


def _guarded(app: FastAPI, inner):
    """ASGI wrapper: the MCP transport sits behind the same authentication as the REST API."""
    async def guarded(scope, receive, send):
        if scope["type"] == "http":
            try:
                principal = principal_from_headers(app.state.settings, app.state.principals, Headers(scope=scope))
                ACTOR.set(principal.name)   # tools that act do so as the caller
            except AuthError as exc:
                body = json.dumps({"detail": str(exc)}).encode()
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        await inner(scope, receive, send)
    return guarded


def _handler(code: int):
    async def handle(request: Request, exc: Exception):
        return JSONResponse(status_code=code, content={"detail": str(exc)})
    return handle


def _llm_provider(settings: Settings) -> LLMProvider | None:
    if settings.llm_provider == "anthropic":
        return AnthropicProvider(model=settings.llm_model)
    if settings.llm_provider == "azure_openai":
        return AzureOpenAIProvider(deployment=settings.azure_openai_deployment, api_key=settings.azure_openai_api_key,
                                   endpoint=settings.azure_openai_endpoint, api_version=settings.azure_openai_api_version)
    return None


def _connections_backend(settings: Settings, hub_client=None):
    """The Polestar connection module, a separate service; nothing local stands in for it."""
    if not settings.connections_hub_url and hub_client is None:
        return NoConnectionModule()
    if hub_client is None:
        headers = {"Authorization": f"Bearer {settings.connections_hub_token}"} if settings.connections_hub_token else {}
        hub_client = httpx.Client(base_url=settings.connections_hub_url.rstrip("/"), headers=headers, timeout=httpx.Timeout(180.0, connect=10.0))
    return HubConnections(hub_client, service_token=settings.connections_hub_service_token)


def _source_engine(settings: Settings, db: Database) -> SourceEngine:
    if settings.source_kind == "databricks":
        missing = [k for k in ("databricks_host", "databricks_http_path", "databricks_token") if not getattr(settings, k)]
        if missing:
            raise ValueError("ONTOFORGE_SOURCE_KIND=databricks needs " + ", ".join(f"ONTOFORGE_{m.upper()}" for m in missing))
        connect = databricks_connect_factory(settings.databricks_host, settings.databricks_http_path, settings.databricks_token,
                                             settings.databricks_catalog, settings.databricks_schema)
        return DatabricksSource(connect, settings.databricks_catalog, settings.databricks_schema)
    if settings.source_kind == "postgres":
        return PostgresSource(db)
    raise ValueError(f"Unknown ONTOFORGE_SOURCE_KIND {settings.source_kind!r}")


def create_app_from_settings() -> FastAPI:
    """Production entry point: ``uvicorn ontoforge.api.main:app``."""
    settings = load_settings()
    db = Database(settings.database_url, schema=settings.database_schema)

    llm = _llm_provider(settings)
    run_migrations(db)
    app = create_app(db, settings=settings, llm=llm)
    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with inner(app):
            yield
        db.close()

    app.router.lifespan_context = lifespan
    return app
