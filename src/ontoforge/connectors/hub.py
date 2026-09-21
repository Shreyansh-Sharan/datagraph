"""Read-only client for the Polestar connection module (the hub), a separate microservice.

The hub owns connections end to end (forms, credentials, tests, browse); the UI talks to it
through its ``@polestar/connections`` package. datagraph only needs to *read* what the hub
knows: the connector types (for the Home cards and the domain pickers), a connection's
masked config (for a domain's source facts) and, on request, a test of a saved connection.
Creating, editing and deleting connections is not proxied here on purpose: that is the
package's job, and duplicating it would make datagraph a second place credentials pass.
"""
from __future__ import annotations

from typing import Any

import httpx

from ontoforge.registry import LifecycleError, NotFound

MASK = "********"


class HubUnavailable(RuntimeError):
    """The hub answered with an error datagraph cannot translate, or not at all."""


class NoConnectionModule:
    """Backend used when ONTOFORGE_CONNECTIONS_HUB_URL is unset: every call says so plainly."""

    source = "none"
    MESSAGE = ("The connection module is not configured: set ONTOFORGE_CONNECTIONS_HUB_URL to the "
               "mf-studio-connectors hub (e.g. http://localhost:8025) to manage connections.")

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)

        def missing(*args, **kwargs):
            raise HubUnavailable(self.MESSAGE)
        return missing


def spec_from_schema(kind: str, category: str, display_name: str, schema: dict) -> dict:
    """Map a connector's JSON Schema (draft 7, as the hub serves it) onto the UI's field spec."""
    props: dict[str, dict] = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    fields, secret_field = [], None
    for name, spec in props.items():
        if not isinstance(spec, dict):
            continue
        secret = spec.get("format") == "password" or spec.get("writeOnly") is True or spec.get("x-secret") is True
        if secret and secret_field is None:
            secret_field = name
        if secret:
            field_kind = "password"
        elif spec.get("enum"):
            field_kind = "select"
        elif spec.get("type") in ("integer", "number"):
            field_kind = "number"
        else:
            field_kind = "text"
        fields.append({"name": name, "label": spec.get("title") or name, "kind": field_kind, "required": name in required and not secret,
                       "default": spec.get("default"), "options": list(spec.get("enum") or []), "help": spec.get("description"),
                       "option_titles": spec.get("x-enum-titles"), "show_when": spec.get("x-show-when")})
    # a secret is entered separately by the form, so it is never a "required" text field
    return {"kind": kind, "label": display_name, "category": "ai" if category == "ai" else "source", "secret_field": secret_field or "",
            "docs": None, "fields": fields, "source": "hub"}


def result_from_report(report: dict) -> dict:
    """Fold the hub's step report into datagraph's TestResult shape."""
    steps = report.get("steps") or []
    failed = [s for s in steps if s.get("status") == "failed"]
    lines = []
    for s in steps:
        line = f"{s.get('name')}: {s.get('status')}"
        if s.get("summary"):
            line += f" · {s['summary']}"
        if s.get("error"):
            line += f" · {s['error']}"
        lines.append(line)
    ok = bool(report.get("ok"))
    title = "Connected" if ok else ((failed[0].get("summary") if failed else None) or "Connection failed")
    action = next((s.get("remediation") for s in failed if s.get("remediation")), None)
    return {"ok": ok, "title": title, "detail": "\n".join(lines), "latency_ms": sum(int(s.get("duration_ms") or 0) for s in steps),
            "action": action, "facts": {"steps": steps}}


class HubConnections:
    """Connections backend over the hub's REST API (see mf-studio-connectors README)."""

    source = "hub"

    def __init__(self, client: httpx.Client) -> None:
        self.http = client
        self._types: dict[str, dict] | None = None

    # -- transport ----------------------------------------------------------------

    def _call(self, method: str, path: str, *, json: Any = None, actor: str | None = None) -> Any:
        headers = {"X-Actor": actor} if actor else {}
        try:
            r = self.http.request(method, path, json=json, headers=headers)
        except httpx.HTTPError as e:
            raise HubUnavailable(f"Connection hub unreachable: {e}") from e
        if r.status_code == 204:
            return None
        if r.is_success:
            return r.json()
        try:
            body = r.json()
        except ValueError:
            body = {"detail": r.text[:300]}
        detail = body.get("detail")
        if isinstance(detail, dict):   # FastAPI HTTPException carrying a dict
            body = {**body, **detail}
            detail = detail.get("detail")
        message = detail if isinstance(detail, str) else str(detail or body)
        if r.status_code == 422:
            errors = body.get("errors") or []
            raise ValueError(message + (": " + "; ".join(errors) if errors else ""))
        if r.status_code == 404:
            raise NotFound(message)
        if r.status_code == 409:
            raise LifecycleError(message)
        raise HubUnavailable(f"Connection hub returned {r.status_code}: {message}")

    # -- connector types ------------------------------------------------------------

    def _type_index(self) -> dict[str, dict]:
        if self._types is None:
            self._types = {t["type"]: t for t in self._call("GET", "/connection-types")}
        return self._types

    def specs(self) -> list[dict]:
        out = []
        for t in self._type_index().values():
            schema = self._call("GET", f"/connection-types/{t['type']}/schema")
            out.append(spec_from_schema(t["type"], t.get("category", ""), t.get("display_name") or t["type"], schema))
        return out

    def spec(self, kind: str) -> dict:
        t = self._type_index().get(kind)
        if t is None:
            self._types = None
            t = self._type_index().get(kind)
        if t is None:
            raise ValueError(f"Unknown connection kind {kind!r}; the hub offers {', '.join(sorted(self._type_index()))}")
        return spec_from_schema(kind, t.get("category", ""), t.get("display_name") or kind, self._call("GET", f"/connection-types/{kind}/schema"))

    def category(self, kind: str) -> str:
        """"ai" or "source" for a connector type (unknown types count as sources)."""
        t = self._type_index().get(kind)
        if t is None:
            self._types = None
            t = self._type_index().get(kind)
        return "ai" if t and t.get("category") == "ai" else "source"

    # -- connections ------------------------------------------------------------------

    @staticmethod
    def _public(c: dict) -> dict:
        config = c.get("config") or {}
        ok = c.get("last_test_ok")
        return {"id": c["id"], "name": c["name"], "kind": c["type"], "config": {k: v for k, v in config.items() if v != MASK},
                "has_secret": any(v == MASK for v in config.values()),
                "last_test": {"ok": bool(ok), "title": "Connected" if ok else "Failed", "detail": "", "at": c.get("last_tested_at")} if ok is not None else None,
                "created_by": None, "created_at": c.get("created_at"), "updated_at": c.get("updated_at"), "source": "hub"}

    def list(self) -> list[dict]:
        return [self._public(c) for c in self._call("GET", "/connections")]

    def get(self, connection_id: str) -> dict:
        return self._public(self._call("GET", f"/connections/{connection_id}"))

    def test(self, connection_id: str, actor: str | None = None) -> dict:
        return result_from_report(self._call("POST", f"/connections/{connection_id}/test", actor=actor))
