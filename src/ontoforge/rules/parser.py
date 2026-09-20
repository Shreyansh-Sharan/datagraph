"""Parser for the SWRL presentation syntax used in rule text."""
from __future__ import annotations

import re

from ontoforge.ontology import Ontology

from .model import BUILTINS, Atom, Rule, RuleError

_ATOM = re.compile(r"\s*([A-Za-z_][\w:.\-]*|<[^>]+>)\s*\((.*?)\)\s*$", re.S)
_ARG = re.compile(r'''\s*(\?[A-Za-z_]\w*|"(?:[^"\\]|\\.)*"|<[^>]+>|-?\d+(?:\.\d+)?|[A-Za-z_][\w:.\-]*)\s*(?:,|$)''')


def parse_rule(text: str, ontology: Ontology, name: str = "rule", mode: str = "materialize", enabled: bool = True) -> Rule:
    if "->" not in text:
        raise RuleError("A rule needs '->' separating body and head")
    body_text, head_text = text.split("->", 1)
    body = tuple(_atom(t, ontology) for t in _split(body_text))
    head = tuple(_atom(t, ontology) for t in _split(head_text))
    return Rule(name, body, head, mode, enabled, text.strip())


def _split(text: str) -> list[str]:
    parts = [p.strip() for p in text.split("^")]
    if any(not p for p in parts):
        raise RuleError(f"Empty atom in {text.strip()!r}")
    return parts


def _atom(text: str, o: Ontology) -> Atom:
    m = _ATOM.match(text)
    if not m:
        raise RuleError(f"Cannot parse atom {text!r}")
    name, raw_args = m.group(1), m.group(2)
    args = tuple(_args(raw_args))
    if name.startswith("swrlb:"):
        builtin = name[6:]
        if builtin not in BUILTINS:
            raise RuleError(f"Unknown built-in {name}; supported: {', '.join('swrlb:' + b for b in BUILTINS)}")
        if len(args) != 2:
            raise RuleError(f"{name} takes two arguments")
        return Atom("builtin", builtin, args)
    iri = name[1:-1] if name.startswith("<") else None
    if len(args) == 1:
        cls = iri or _resolve(name, o.classes, "class")
        return Atom("class", cls, args)
    if len(args) == 2:
        prop = iri or _resolve(name, {p.iri: p for p in o.all_properties()}, "property")
        return Atom("property", prop, args)
    raise RuleError(f"Atom {name} must have one (class) or two (property) arguments")


def _resolve(name: str, table: dict, what: str) -> str:
    if name in table:
        return name
    hits = [iri for iri in table if Ontology.local_name(iri) == name]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise RuleError(f"Unknown {what} {name}")
    raise RuleError(f"Ambiguous {what} name {name}: {', '.join(hits)}")


def _args(raw: str):
    pos = 0
    raw = raw.strip()
    while pos < len(raw):
        m = _ARG.match(raw, pos)
        if not m:
            raise RuleError(f"Cannot parse arguments {raw!r}")
        tok = m.group(1)
        pos = m.end()
        if tok.startswith("?"):
            yield tok
        elif tok.startswith('"'):
            yield tok[1:-1].replace('\\"', '"')
        elif tok.startswith("<"):
            yield tok[1:-1]
        elif re.fullmatch(r"-?\d+", tok):
            yield int(tok)
        elif re.fullmatch(r"-?\d+\.\d+", tok):
            yield float(tok)
        else:
            raise RuleError(f"Unexpected argument {tok!r}: use ?var, a number, a \"string\" or an <iri>")
