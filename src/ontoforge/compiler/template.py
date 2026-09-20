"""R2RML string templates (§7.3): literal text interleaved with {column} references.

Backslash escapes a brace (``\\{`` / ``\\}``) or itself. Column names inside braces follow
SQL identifier rules, so ``{"First Name"}`` refers to the delimited column ``First Name``.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnRef:
    name: str


TemplatePart = str | ColumnRef


def parse_template(template: str) -> tuple[TemplatePart, ...]:
    parts: list[TemplatePart] = []
    buf: list[str] = []
    i, n = 0, len(template)
    while i < n:
        ch = template[i]
        if ch == "\\" and i + 1 < n and template[i + 1] in "{}\\":
            buf.append(template[i + 1])
            i += 2
        elif ch == "{":
            end = template.find("}", i + 1)
            if end < 0:
                raise ValueError(f"Unbalanced '{{' in template {template!r}")
            if buf:
                parts.append("".join(buf))
                buf = []
            name = template[i + 1:end]
            if not name:
                raise ValueError(f"Empty column reference in template {template!r}")
            if len(name) >= 2 and name[0] == name[-1] == '"':
                name = name[1:-1].replace('""', '"')
            parts.append(ColumnRef(name))
            i = end + 1
        elif ch == "}":
            raise ValueError(f"Unbalanced '}}' in template {template!r}")
        else:
            buf.append(ch)
            i += 1
    if buf:
        parts.append("".join(buf))
    return tuple(parts)


def template_columns(template: str) -> tuple[str, ...]:
    return tuple(p.name for p in parse_template(template) if isinstance(p, ColumnRef))
