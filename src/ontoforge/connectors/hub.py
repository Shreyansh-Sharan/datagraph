"""The Polestar connection module (hub) as the connections backend.

When ``ONTOFORGE_CONNECTIONS_HUB_URL`` is set, the Configure screen's connectors and
connections come from the hub instead of the local ``connections`` table: connector specs
are derived from the hub's JSON Schemas, secrets never touch datagraph, and a domain's
``connection_id`` is a hub connection id. Test reports (one step per check) are folded into
the same result shape the local adapters return, so the UI does not know which backend it
is talking to.
"""
from __future__ import annotations

from typing import Any

import httpx

from ontoforge.registry import LifecycleError, NotFound

MASK = "********"


class HubUnavailable(RuntimeError):
    """The hub answered with an error datagraph cannot translate, or not at all."""


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

    # -- connections ------------------------------------------------------------------

    @staticmethod
    def _public(c: dict) -> dict:
        config = c.get("config") or {}
        ok = c.get("last_test_ok")
        return {"id": c["id"], "name": c["name"], "kind": c["type"], "config": {k: v for k, v in config.items() if v != MASK},
                "has_secret": any(v == MASK for v in config.values()),
                "last_test": {"ok": bool(ok), "title": "Connected" if ok else "Failed", "detail": "", "at": c.get("last_tested_at")} if ok is not None else None,
                "created_by": None, "created_at": c.get("created_at"), "updated_at": c.get("updated_at"), "source": "hub"}

    def _payload(self, kind: str, config: dict, secret: str | None) -> dict:
        spec = self.spec(kind)
        cfg = {k: v for k, v in config.items() if v != MASK}
        if secret and spec["secret_field"]:
            cfg[spec["secret_field"]] = secret
        return cfg

    def list(self) -> list[dict]:
        return [self._public(c) for c in self._call("GET", "/connections")]

    def get(self, connection_id: str) -> dict:
        return self._public(self._call("GET", f"/connections/{connection_id}"))

    def create(self, name: str, kind: str, config: dict, secret: str | None, actor: str | None = None) -> dict:
        return self._public(self._call("POST", "/connections", json={"name": name, "type": kind, "config": self._payload(kind, config, secret)}, actor=actor))

    def update(self, connection_id: str, *, name: str | None = None, config: dict | None = None, secret: str | None = None, actor: str | None = None) -> dict:
        current = self._call("GET", f"/connections/{connection_id}")
        body: dict = {}
        if name is not None:
            body["name"] = name
        if config is not None or secret:
            body["config"] = self._payload(current["type"], config if config is not None else current.get("config") or {}, secret)
        return self._public(self._call("PATCH", f"/connections/{connection_id}", json=body, actor=actor))

    def delete(self, connection_id: str, actor: str | None = None) -> None:
        self._call("DELETE", f"/connections/{connection_id}", actor=actor)

    def test_draft(self, kind: str, config: dict, secret: str | None) -> dict:
        return result_from_report(self._call("POST", "/connection-types/test", json={"type": kind, "config": self._payload(kind, config, secret)}))

    def test(self, connection_id: str, actor: str | None = None) -> dict:
        return result_from_report(self._call("POST", f"/connections/{connection_id}/test", actor=actor))
