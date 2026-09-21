"""The local ``connections`` table as the connections backend (no hub configured)."""
from __future__ import annotations

from uuid import UUID

from ontoforge.registry import NotFound, Registry

from . import connector, specs
from .secrets import SecretBox


def _uuid(connection_id: str) -> UUID:
    try:
        return UUID(str(connection_id))
    except ValueError:
        raise NotFound(f"Connection {connection_id}") from None


class LocalConnections:
    source = "local"

    def __init__(self, registry: Registry, secrets: SecretBox) -> None:
        self.registry = registry
        self.secrets = secrets

    @staticmethod
    def _public(c) -> dict:
        return {**c.public(), "id": str(c.id), "source": "local"}

    def specs(self) -> list[dict]:
        return [{**s, "source": "local"} for s in specs()]

    def spec(self, kind: str) -> dict:
        return {**connector(kind).spec.to_dict(), "source": "local"}

    def list(self) -> list[dict]:
        return [self._public(c) for c in self.registry.list_connections()]

    def get(self, connection_id: str) -> dict:
        return self._public(self.registry.get_connection(_uuid(connection_id)))

    def _split(self, kind: str, config: dict, secret: str | None) -> tuple[dict, str | None]:
        spec = connector(kind).spec
        clean = spec.validate(config)
        secret = secret or config.get(spec.secret_field)
        clean.pop(spec.secret_field, None)
        return clean, secret

    def create(self, name: str, kind: str, config: dict, secret: str | None, actor: str | None = None) -> dict:
        clean, secret = self._split(kind, config, secret)
        return self._public(self.registry.create_connection(name, kind, clean, self.secrets.encrypt(secret), actor=actor))

    def update(self, connection_id: str, *, name: str | None = None, config: dict | None = None, secret: str | None = None, actor: str | None = None) -> dict:
        current = self.registry.get_connection(_uuid(connection_id))
        clean = None
        if config is not None:
            clean, secret = self._split(current.kind, config, secret)
        return self._public(self.registry.update_connection(current.id, name=name, config=clean, secret=self.secrets.encrypt(secret), actor=actor))

    def delete(self, connection_id: str, actor: str | None = None) -> None:
        self.registry.delete_connection(_uuid(connection_id), actor=actor)

    def test_draft(self, kind: str, config: dict, secret: str | None) -> dict:
        clean, secret = self._split(kind, config, secret)
        return connector(kind).test(clean, secret).to_dict()

    def test(self, connection_id: str, actor: str | None = None) -> dict:
        c = self.registry.get_connection(_uuid(connection_id))
        result = connector(c.kind).test(c.config, self.secrets.decrypt(c.secret)).to_dict()
        self.registry.record_connection_test(c.id, result)
        return result
