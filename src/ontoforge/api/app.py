"""FastAPI application factory. All state hangs off ``app.state``; routes read it via ``deps``."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ontoforge.auth import AuthError, Forbidden, Principals
from ontoforge.build import BuildPipeline, BuildScheduler, DatabricksSource, PostgresSource, SourceEngine, databricks_connect_factory
from ontoforge.compiler import CompileError, IdentifierError
from ontoforge.config import Settings, load_settings
from ontoforge.db import Database, run_migrations
from ontoforge.llm import AnthropicProvider, LLMOutputError, LLMProvider, LLMUnavailable
from ontoforge.mapping import MappingSpecError
from ontoforge.r2rml import MappingError
from ontoforge.reasoning import Reasoner
from ontoforge.registry import LifecycleError, LockedError, NotFound, Registry
from ontoforge.store import TripleStore

from .routes import open_router, router

_STATUS = {AuthError: 401, Forbidden: 403, NotFound: 404, LifecycleError: 409, LockedError: 423, LLMUnavailable: 503, LLMOutputError: 502,
           MappingSpecError: 400, MappingError: 400, CompileError: 400, IdentifierError: 400, ValueError: 400}


def create_app(db: Database, source_db: Database | None = None, settings: Settings | None = None,
               llm: LLMProvider | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="ontoforge", version="0.1.0")
    app.state.settings = settings
    app.state.db = db
    app.state.registry = Registry(db)
    app.state.principals = Principals(db)
    app.state.store = TripleStore(db)
    app.state.source = _source_engine(settings, source_db or db)
    app.state.pipeline = BuildPipeline(app.state.registry, app.state.store, app.state.source)
    app.state.scheduler = BuildScheduler(app.state.pipeline, app.state.registry, workers=settings.build_workers)
    app.state.reasoner = Reasoner(app.state.registry, app.state.store)
    app.state.llm = llm
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.registry.fail_stale_builds()   # no worker survives a restart
        yield
        app.state.scheduler.shutdown(wait=False)

    app.router.lifespan_context = lifespan
    app.include_router(open_router)
    app.include_router(router)

    for cls, code in _STATUS.items():
        app.add_exception_handler(cls, _handler(code))
    return app


def _handler(code: int):
    async def handle(request: Request, exc: Exception):
        return JSONResponse(status_code=code, content={"detail": str(exc)})
    return handle


def _source_engine(settings: Settings, db: Database) -> SourceEngine:
    if settings.source_kind == "databricks":
        missing = [k for k in ("databricks_host", "databricks_http_path", "databricks_token") if not getattr(settings, k)]
        if missing:
            raise ValueError("ONTOFORGE_SOURCE_KIND=databricks needs " + ", ".join(f"ONTOFORGE_{m.upper()}" for m in missing))
        connect = databricks_connect_factory(settings.databricks_host, settings.databricks_http_path, settings.databricks_token)
        return DatabricksSource(connect, settings.databricks_catalog, settings.databricks_schema)
    if settings.source_kind == "postgres":
        return PostgresSource(db)
    raise ValueError(f"Unknown ONTOFORGE_SOURCE_KIND {settings.source_kind!r}")


def create_app_from_settings() -> FastAPI:
    """Production entry point: ``uvicorn ontoforge.api.main:app``."""
    settings = load_settings()
    db = Database(settings.database_url, schema=settings.database_schema)

    llm = AnthropicProvider(model=settings.llm_model) if settings.llm_provider == "anthropic" else None
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
