"""Strict SQL identifier validation.

Mapping documents are user-authored and become executable SQL, so every identifier is
validated against a conservative grammar before it is quoted by a dialect. Delimited
identifiers (``"..."``) are unwrapped and may contain any character except a double quote
or control characters; the dialect re-quotes them safely.
"""
from __future__ import annotations

import re


class IdentifierError(ValueError):
    """An identifier is empty, malformed, or looks like an injection attempt."""


_BARE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def validate_column(name: str) -> str:
    """Return the canonical (unquoted) column name or raise IdentifierError."""
    return _validate_part(name, what="column")


def validate_table(name: str) -> tuple[str, ...]:
    """Return the dotted parts (up to catalog.schema.table) or raise IdentifierError."""
    if not name or not name.strip():
        raise IdentifierError("Empty table name")
    parts = _split_dotted(name)
    if not 1 <= len(parts) <= 3:
        raise IdentifierError(f"Table name {name!r} must have 1 to 3 dotted parts")
    return tuple(_validate_part(p, what="table") for p in parts)


def _validate_part(name: str, *, what: str) -> str:
    if not name:
        raise IdentifierError(f"Empty {what} name")
    if len(name) >= 2 and name[0] == name[-1] == '"':
        inner = name[1:-1].replace('""', '\x00')
        if '"' in inner or _CONTROL.search(inner.replace('\x00', '')) or not inner:
            raise IdentifierError(f"Malformed delimited {what} name {name!r}")
        return inner.replace('\x00', '"')
    if not _BARE.match(name):
        raise IdentifierError(f"Invalid {what} name {name!r}: use letters, digits, '_' or a \"delimited\" name")
    return name


def _split_dotted(name: str) -> list[str]:
    """Split on dots that are outside double quotes."""
    parts, buf, quoted = [], [], False
    for ch in name:
        if ch == '"':
            quoted = not quoted
        if ch == "." and not quoted:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts
