"""Compile rules to SQL over the ``triples`` table and run them.

Each class/property body atom becomes one join on ``triples``; shared variables become equality
predicates; built-ins become WHERE clauses. Materialisation inserts the head triples that do not
exist yet (flagged ``inferred``) and iterates to a fixpoint so rules can feed each other.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from uuid import UUID

from ontoforge.compiler import RDF_TYPE
from ontoforge.dialects import PostgresDialect
from ontoforge.registry import Registry
from ontoforge.store import TripleStore

from .model import Atom, Rule, RuleError, RuleSet

_NUMERIC = r"'^-?[0-9]+(\.[0-9]+)?$'"
_OPS = {"equal": "=", "notEqual": "<>", "lessThan": "<", "lessThanOrEqual": "<=", "greaterThan": ">", "greaterThanOrEqual": ">="}
_D = PostgresDialect()


@dataclass
class RuleReport:
    materialised: int = 0
    iterations: int = 0
    per_rule: dict[str, int] = field(default_factory=dict)
    violations: list[dict] = field(default_factory=list)


class _Compiled:
    """Bindings for one rule body: FROM/JOIN clauses, WHERE predicates, variable expressions."""

    def __init__(self, rule: Rule, version_id: UUID) -> None:
        self.rule, self.vid = rule, _D.string_literal(str(version_id))
        self.tables: list[str] = []
        self.where: list[str] = []
        self.vars: dict[str, tuple[str, str]] = {}   # ?x -> (expr, position 'subject'|'object')
        for atom in rule.body:
            if atom.kind == "builtin":
                continue
            alias = f"t{len(self.tables)}"
            self.tables.append(alias)
            self.where.append(f"{alias}.domain_version_id = {self.vid}")
            if atom.kind == "class":
                self.where.append(f"{alias}.predicate = {_D.string_literal(RDF_TYPE)}")
                self.where.append(f"{alias}.object = {_D.string_literal(atom.predicate)}")
                self._bind(atom.args[0], f"{alias}.subject", "subject")
            else:
                self.where.append(f"{alias}.predicate = {_D.string_literal(atom.predicate)}")
                self._bind(atom.args[0], f"{alias}.subject", "subject")
                self._bind(atom.args[1], f"{alias}.object", "object")
        for atom in rule.body:
            if atom.kind == "builtin":
                self.where.append(self._builtin(atom))

    def _bind(self, arg, expr: str, position: str) -> None:
        if isinstance(arg, str) and arg.startswith("?"):
            if arg in self.vars:
                self.where.append(f"{expr} = {self.vars[arg][0]}")
            else:
                self.vars[arg] = (expr, position)
        else:
            self.where.append(f"{expr} = {_D.string_literal(str(arg))}")

    def _builtin(self, atom: Atom) -> str:
        a, b = atom.args
        numeric = any(isinstance(x, (int, float)) for x in (a, b))
        left, right = self._value(a, numeric), self._value(b, numeric)
        return f"{left} {_OPS[atom.predicate]} {right}"

    def _value(self, arg, numeric: bool) -> str:
        if isinstance(arg, (int, float)):
            return str(arg)
        if arg.startswith("?"):
            expr, position = self.vars[arg]
            if not numeric:
                return expr
            guard = f"{expr.split('.')[0]}.object_type = 'literal' AND " if position == "object" else ""
            return f"(CASE WHEN {guard}{expr} ~ {_NUMERIC} THEN CAST({expr} AS numeric) END)"
        return _D.string_literal(arg)

    def from_clause(self) -> str:
        return " CROSS JOIN ".join(f"triples {t}" for t in self.tables) if self.tables else ""

    def select_bindings(self) -> str:
        cols = ", ".join(f"{expr} AS {_D.quote_identifier(v[1:])}" for v, (expr, _) in self.vars.items())
        sql = f"SELECT DISTINCT {cols}\nFROM {self.from_clause()}"
        if self.where:
            sql += "\nWHERE " + " AND ".join(self.where)
        return sql

    def head_rows(self, atom: Atom) -> tuple[str, str, str, str, str]:
        """(subject, predicate, object, object_type, datatype) expressions for one head atom."""
        if atom.kind == "class":
            return (self._term(atom.args[0])[0], _D.string_literal(RDF_TYPE), _D.string_literal(atom.predicate), "'iri'", "NULL")
        s, _ = self._term(atom.args[0])
        o, pos = self._term(atom.args[1])
        if pos == "object":
            alias = o.split(".")[0]
            return (s, _D.string_literal(atom.predicate), o, f"{alias}.object_type", f"{alias}.datatype")
        obj_type = "'iri'" if pos == "subject" else "'literal'"
        return (s, _D.string_literal(atom.predicate), o, obj_type, "NULL")

    def _term(self, arg) -> tuple[str, str]:
        if isinstance(arg, str) and arg.startswith("?"):
            return self.vars[arg]
        return _D.string_literal(str(arg)), "const"

    def insert_missing(self, atom: Atom) -> str:
        s, p, o, ot, dt = self.head_rows(atom)
        where = list(self.where) + [
            f"NOT EXISTS (SELECT 1 FROM triples x WHERE x.domain_version_id = {self.vid} AND x.subject = {s} "
            f"AND x.predicate = {p} AND x.object = {o})"]
        return (f"INSERT INTO triples (domain_version_id, subject, predicate, object, object_type, datatype, lang, inferred)\n"
                f"SELECT DISTINCT CAST({self.vid} AS uuid), {s}, {p}, {o}, {ot}, {dt}, NULL, true\nFROM {self.from_clause()}\n"
                f"WHERE " + " AND ".join(where))


class RuleEngine:
    MAX_ITERATIONS = 25

    def __init__(self, registry: Registry, store: TripleStore) -> None:
        self.registry, self.store = registry, store

    @staticmethod
    def compile_select(rule: Rule, version_id: UUID | str) -> str:
        return _Compiled(rule, version_id).select_bindings()

    @staticmethod
    def compile_insert(rule: Rule, version_id: UUID | str) -> list[str]:
        c = _Compiled(rule, version_id)
        return [c.insert_missing(atom) for atom in rule.head]

    def rules_for(self, version_id: UUID) -> RuleSet:
        return RuleSet.from_dict(self.registry.get_version(version_id).rules)

    def materialise(self, version_id: UUID) -> RuleReport:
        rules = self.rules_for(version_id).enabled("materialize")
        report = RuleReport(per_rule={r.name: 0 for r in rules})
        if not rules:
            return report
        statements = {r.name: self.compile_insert(r, version_id) for r in rules}
        for _ in range(self.MAX_ITERATIONS):
            report.iterations += 1
            added = 0
            with self.store.db.transaction() as cur:
                for r in rules:
                    for stmt in statements[r.name]:
                        cur.execute(stmt)
                        report.per_rule[r.name] += cur.rowcount
                        added += cur.rowcount
            report.materialised += added
            if added == 0:
                break
        return report

    def check(self, version_id: UUID) -> RuleReport:
        report = RuleReport()
        with self.store.db.transaction() as cur:
            for r in self.rules_for(version_id).enabled("violation"):
                cur.execute(self.compile_select(r, version_id))
                cols = [d.name for d in cur.description]
                for row in cur.fetchall():
                    report.violations.append({"rule": r.name, "bindings": dict(zip(cols, (str(v) for v in row)))})
        return report

    def run(self, version_id: UUID) -> RuleReport:
        report = self.materialise(version_id)
        report.violations = self.check(version_id).violations
        return report
