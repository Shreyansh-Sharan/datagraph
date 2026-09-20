"""FastAPI application factory. All state hangs off ``app.state``; routes read it via ``deps``."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ontoforge.build import BuildPipeline, PostgresSource
from ontoforge.compiler import CompileError, IdentifierError
from ontoforge.config import Settings, load_settings
from ontoforge.db import Database, run_migrations
from ontoforge.mapping import MappingSpecError
from ontoforge.r2rml import MappingError
from ontoforge.reasoning import Reasoner
from ontoforge.registry import LifecycleError, LockedError, NotFound, Registry
from ontoforge.store import TripleStore

from .routes import router

_STATUS = {NotFound: 404, LifecycleError: 409, LockedError: 423, MappingSpecError: 400, MappingError: 400,
           CompileError: 400, IdentifierError: 400, ValueError: 400}


def create_app(db: Database, source_db: Database | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="ontoforge", version="0.1.0")
    app.state.settings = settings
    app.state.db = db
    app.state.registry = Registry(db)
    app.state.store = TripleStore(db)
    app.state.source = PostgresSource(source_db or db)
    app.state.pipeline = BuildPipeline(app.state.registry, app.state.store, app.state.source)
    app.state.reasoner = Reasoner(app.state.registry, app.state.store)
    app.include_router(router)

    for cls, code in _STATUS.items():
        app.add_exception_handler(cls, _handler(code))
    return app


def _handler(code: int):
    async def handle(request: Request, exc: Exception):
        return JSONResponse(status_code=code, content={"detail": str(exc)})
    return handle


def create_app_from_settings() -> FastAPI:
    """Production entry point: ``uvicorn ontoforge.api.main:app``."""
    settings = load_settings()
    db = Database(settings.database_url, schema=settings.database_schema)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        run_migrations(db)
        yield
        db.close()

    app = create_app(db, settings=settings)
    app.router.lifespan_context = lifespan
    return app
