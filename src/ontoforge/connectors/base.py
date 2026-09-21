from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str = "text"              # text | password | number | select
    required: bool = True
    default: str | int | None = None
    options: tuple[str, ...] = ()
    help: str | None = None


@dataclass(frozen=True)
class ConnectorSpec:
    kind: str
    label: str
    category: str                   # "source" | "ai"
    fields: tuple[Field, ...]
    secret_field: str               # the one field stored encrypted (token, password, api key)
    docs: str | None = None

    def to_dict(self) -> dict:
        return {"kind": self.kind, "label": self.label, "category": self.category, "secret_field": self.secret_field, "docs": self.docs,
                "fields": [{k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(f).items()} for f in self.fields]}

    def validate(self, config: dict) -> dict:
        """Keep known fields only, apply defaults, coerce numbers, and require what is required."""
        clean: dict = {}
        for f in self.fields:
            v = config.get(f.name, f.default)
            if v in (None, "") and f.required:
                raise ValueError(f"{self.label}: {f.label} is required")
            if v in (None, ""):
                continue
            if f.kind == "number":
                try:
                    v = int(v)
                except (TypeError, ValueError):
                    raise ValueError(f"{self.label}: {f.label} must be a number") from None
            if f.kind == "select" and f.options and v not in f.options:
                raise ValueError(f"{self.label}: {f.label} must be one of {', '.join(f.options)}")
            clean[f.name] = v
        return clean


@dataclass
class TestResult:
    ok: bool
    title: str
    detail: str
    latency_ms: int = 0
    action: str | None = None        # what the user can do about a failure
    facts: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class Connector(ABC):
    spec: ConnectorSpec

    @abstractmethod
    def _probe(self, config: dict, secret: str | None) -> TestResult:
        """Open a connection and run the cheapest meaningful call; raise on failure."""

    def test(self, config: dict, secret: str | None) -> TestResult:
        t0 = time.perf_counter()
        try:
            result = self._probe(config, secret)
        except Exception as e:  # provider errors are surfaced verbatim, never swallowed
            result = self.failure(e)
        result.latency_ms = int((time.perf_counter() - t0) * 1000)
        return result

    def failure(self, e: Exception) -> TestResult:
        msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
        return TestResult(False, "Connection failed", msg, action=self.advice(msg))

    def advice(self, message: str) -> str | None:
        return None
