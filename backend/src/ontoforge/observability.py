"""Structured logging and request timing.

``configure_logging("json")`` makes every ontoforge log line one JSON object; ``"text"`` keeps the
usual console format. ``RequestLoggingMiddleware`` assigns/echoes ``X-Request-ID`` and logs
method, path, status, duration and actor for every non-infrastructure request. The request id is
kept in a contextvar so any log record emitted while serving the request carries it.
"""
from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
_SKIP_PATHS = {"/health", "/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}
_STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
            "msg": record.getMessage(),
        }
        rid = getattr(record, "request_id", None) or request_id_var.get()
        if rid:
            out["request_id"] = rid
        for key, value in record.__dict__.items():   # extra= fields
            if key not in _STANDARD and key not in out and not key.startswith("_"):
                out[key] = value
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        return True


def configure_logging(fmt: str = "text", level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("ontoforge")
    for h in list(logger.handlers):
        logger.removeHandler(h)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if fmt == "json" else
                         logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(_RequestIdFilter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = True  # so pytest's caplog / root handlers still see records
    return logger


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, identity_header: str = "X-Actor") -> None:
        super().__init__(app)
        self.identity_header = identity_header
        self.log = logging.getLogger("ontoforge.http")

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = request_id_var.set(rid)
        t0 = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            if request.url.path not in _SKIP_PATHS:
                self.log.info("%s %s -> %s", request.method, request.url.path, status, extra={
                    "event": "http.request", "method": request.method, "path": request.url.path, "status": status,
                    "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                    "actor": request.headers.get(self.identity_header), "request_id": rid})
            request_id_var.reset(token)
