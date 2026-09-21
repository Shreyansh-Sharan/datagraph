"""Secrets at rest: Fernet (AES-128-CBC + HMAC) under a key derived from ``ONTOFORGE_SECRET_KEY``."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


class SecretBox:
    def __init__(self, key: str) -> None:
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, plain: str | None) -> str | None:
        if plain is None or plain == "":
            return None
        return self._fernet.encrypt(plain.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str | None) -> str | None:
        if not token:
            return None
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            return None
