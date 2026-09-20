"""FastAPI dependencies: resolve the caller, then gate routes by role."""
from __future__ import annotations

from fastapi import Depends, Request

from ontoforge.config import Settings

from .models import AuthError, Principal, Role
from .principals import Principals


def resolve_principal(request: Request) -> Principal:
    return principal_from_headers(request.app.state.settings, request.app.state.principals, request.headers)


def principal_from_headers(settings: Settings, principals: Principals, headers) -> Principal:
    """Shared by the FastAPI dependency and the raw-ASGI guard in front of the MCP mount."""
    if settings.auth_mode == "token":
        header = headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise AuthError("Missing bearer token")
        key = principals.resolve_api_key(header[7:].strip())
        if key is None:
            raise AuthError("Unknown or revoked API key")
        return Principal(key.principal, key.role)
    if settings.auth_mode == "header":
        name = (headers.get(settings.auth_header) or "").strip()
        if not name:
            raise AuthError(f"Missing identity header {settings.auth_header}")
        role = principals.get_role(name) or Role(settings.auth_default_role)
        return Principal(name, role)
    raise AuthError(f"Unknown auth mode {settings.auth_mode!r}")


def current_principal(request: Request) -> Principal:
    return resolve_principal(request)


def _gate(role: Role):
    def dep(me: Principal = Depends(current_principal)) -> Principal:
        me.require(role)
        return me
    return dep


viewer = _gate(Role.VIEWER)
builder = _gate(Role.BUILDER)
reviewer = _gate(Role.REVIEWER)
admin = _gate(Role.ADMIN)
