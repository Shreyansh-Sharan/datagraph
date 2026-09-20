"""FastAPI dependencies: resolve the caller, then gate routes by role."""
from __future__ import annotations

from fastapi import Depends, Request

from ontoforge.config import Settings

from .models import AuthError, Principal, Role
from .principals import Principals


def resolve_principal(request: Request) -> Principal:
    settings: Settings = request.app.state.settings
    principals: Principals = request.app.state.principals
    if settings.auth_mode == "token":
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise AuthError("Missing bearer token")
        key = principals.resolve_api_key(header[7:].strip())
        if key is None:
            raise AuthError("Unknown or revoked API key")
        return Principal(key.principal, key.role)
    if settings.auth_mode == "header":
        name = (request.headers.get(settings.auth_header) or "").strip()
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
