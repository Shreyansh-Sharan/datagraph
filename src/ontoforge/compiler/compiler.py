"""Compile an R2RML Mapping into one SQL statement that yields a triple stream.

Output columns: subject, predicate, object, object_type ('iri' | 'literal' | 'bnode'),
datatype (IRI or NULL), lang (tag or NULL).

Semantics follow W3C R2RML §11 ("Generated RDF"):
  * one SELECT per (triples map, rr:class)             -> rdf:type triples
  * one SELECT per (predicate map, object map) pair    -> data / relationship triples
  * a row contributes no triple when any column used by its subject, predicate or object is NULL
  * referencing object maps become a JOIN on the parent's logical table (or the same row
    when no join condition is given)
  * the SELECTs are combined with UNION ALL
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ontoforge.dialects.base import SqlDialect
from ontoforge.r2rml.model import LogicalTable, Mapping, PredicateObjectMap, RefObjectMap, TermKind, TermMap, TriplesMap

from .identifiers import validate_column
from .template import ColumnRef, parse_template

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
CHILD, PARENT = "t", "p"
OUTPUT_COLUMNS = ("subject", "predicate", "object", "object_type", "datatype", "lang")

ColumnTypeResolver = Callable[[LogicalTable, str], str | None]


class CompileError(ValueError):
    """The mapping is valid R2RML but cannot be compiled safely for this target."""


@dataclass(frozen=True)
class TripleSelect:
    sql: str
    triples_map: str
    predicate: str | None  # constant predicate IRI when known
    tables: tuple[str, ...] = ()   # source tables the rows come from: the child table first, a joined parent second; empty for a query

    @property
    def source_table(self) -> str | None:
        return self.tables[0] if self.tables else None


@dataclass(frozen=True)
class CompiledMapping:
    selects: tuple[TripleSelect, ...]
    dialect: SqlDialect
    columns: tuple[str, ...] = OUTPUT_COLUMNS

    @property
    def sql(self) -> str:
        return "\nUNION ALL\n".join(s.sql for s in self.selects)

    def view_ddl(self, target: str) -> str:
        return f"CREATE OR REPLACE VIEW {self.dialect.quote_table(target)} AS\n{self.sql}"

    def table_ddl(self, target: str) -> str:
        return f"CREATE OR REPLACE TABLE {self.dialect.quote_table(target)} AS\n{self.sql}"


@dataclass(frozen=True)
class _Term:
    """A compiled term map: the SQL for its value plus what must be non-NULL for it to exist."""
    value: str
    kind: TermKind
    required: tuple[str, ...]  # qualified column expressions
    datatype: str | None = None
    language: str | None = None


def _tables(*maps: TriplesMap) -> tuple[str, ...]:
    """The named logical tables behind these triples maps, child first, without repeats; empty when any is a query."""
    names = [m.logical_table.table_name for m in maps]
    if any(n is None for n in names):
        return ()
    return tuple(dict.fromkeys(names))


def compile_mapping(mapping: Mapping, dialect: SqlDialect,
                    column_types: ColumnTypeResolver | None = None) -> CompiledMapping:
    return _Compiler(dialect, column_types).compile(mapping)


class _Compiler:
    def __init__(self, dialect: SqlDialect, column_types: ColumnTypeResolver | None) -> None:
        self.d = dialect
        self.column_types = column_types or (lambda lt, col: None)

    def compile(self, mapping: Mapping) -> CompiledMapping:
        selects: list[TripleSelect] = []
        for tm in mapping.triples_maps.values():
            selects.extend(self._triples_map(tm))
        if not selects:
            raise CompileError("Mapping produces no triples")
        return CompiledMapping(selects=tuple(selects), dialect=self.d)

    # -- per triples map -----------------------------------------------------

    def _triples_map(self, tm: TriplesMap) -> list[TripleSelect]:
        subject = self._term(tm.subject, CHILD, tm.logical_table)
        source = self._source(tm.logical_table, CHILD)
        out = []
        for cls in tm.classes:
            obj = _Term(self.d.string_literal(cls), TermKind.IRI, ())
            pred = _Term(self.d.string_literal(RDF_TYPE), TermKind.IRI, ())
            out.append(TripleSelect(self._select(subject, pred, obj, source, []), tm.iri, RDF_TYPE, _tables(tm)))
        for pom in tm.predicate_object_maps:
            out.extend(self._predicate_object_map(tm, subject, source, pom))
        return out

    def _predicate_object_map(self, tm: TriplesMap, subject: _Term, source: str,
                              pom: PredicateObjectMap) -> list[TripleSelect]:
        out = []
        for pred_map in pom.predicates:
            pred = self._term(pred_map, CHILD, tm.logical_table)
            for obj_map in pom.objects:
                if isinstance(obj_map, RefObjectMap):
                    obj, from_clause, on = self._reference(tm, obj_map)
                    sql = self._select(subject, pred, obj, from_clause, on)
                    tables = _tables(tm, obj_map.parent_triples_map)
                else:
                    obj = self._term(obj_map, CHILD, tm.logical_table)
                    sql = self._select(subject, pred, obj, source, [])
                    tables = _tables(tm)
                out.append(TripleSelect(sql, tm.iri, pred_map.constant if pred_map.is_constant else None, tables))
        return out

    def _reference(self, child: TriplesMap, ref: RefObjectMap) -> tuple[_Term, str, list[str]]:
        parent = ref.parent_triples_map
        if not ref.join_conditions:
            if parent.logical_table != child.logical_table:
                raise CompileError(f"{child.iri}: rr:parentTriplesMap without rr:joinCondition "
                                   "requires identical logical tables")
            return self._term(parent.subject, CHILD, child.logical_table), self._source(child.logical_table, CHILD), []
        on = [f"{self._col(CHILD, c)} = {self._col(PARENT, p)}" for c, p in ref.join_conditions]
        from_clause = f"{self._source(child.logical_table, CHILD)} JOIN {self._source(parent.logical_table, PARENT)}"
        return self._term(parent.subject, PARENT, parent.logical_table), from_clause, on

    # -- SQL assembly --------------------------------------------------------

    def _select(self, s: _Term, p: _Term, o: _Term, from_clause: str, on: list[str]) -> str:
        lit = lambda v: self.d.string_literal(v) if v is not None else self.d.null_text()
        cols = [f"{s.value} AS subject", f"{p.value} AS predicate", f"{o.value} AS object",
                f"{lit(o.kind.value)} AS object_type", f"{lit(o.datatype)} AS datatype", f"{lit(o.language)} AS lang"]
        required = list(dict.fromkeys(s.required + p.required + o.required))
        where = [f"{c} IS NOT NULL" for c in required]
        sql = "SELECT " + ", ".join(cols) + "\nFROM " + from_clause
        if on:
            sql += " ON " + " AND ".join(on)
        if where:
            sql += "\nWHERE " + " AND ".join(where)
        return sql

    def _source(self, lt: LogicalTable, alias: str) -> str:
        if lt.table_name is not None:
            return f"{self.d.quote_table(lt.table_name)} AS {alias}"
        query = (lt.sql_query or "").strip()
        if not query:
            raise CompileError("rr:sqlQuery is empty")
        if ";" in query:
            raise CompileError("rr:sqlQuery must be a single statement without ';'")
        return f"({query}) AS {alias}"

    def _col(self, alias: str, name: str) -> str:
        return f"{alias}.{self.d.quote_identifier(validate_column(name))}"

    # -- term maps -----------------------------------------------------------

    def _term(self, tm: TermMap, alias: str, lt: LogicalTable) -> _Term:
        if tm.constant is not None:
            value = f"_:{tm.constant}" if tm.term_kind is TermKind.BLANK_NODE else tm.constant
            return _Term(self.d.string_literal(value), tm.term_kind, (), tm.datatype, tm.language)
        if tm.column is not None:
            col = self._col(alias, tm.column)
            text = self.d.to_text(col)
            value = self.d.concat([self.d.string_literal("_:"), text]) if tm.term_kind is TermKind.BLANK_NODE else text
            datatype = tm.datatype
            if tm.term_kind is TermKind.LITERAL and datatype is None and tm.language is None:
                sql_type = self.column_types(lt, validate_column(tm.column))
                datatype = self.d.xsd_for_sql_type(sql_type) if sql_type else None
            return _Term(value, tm.term_kind, (col,), datatype, tm.language)
        return self._template_term(tm, alias)

    def _template_term(self, tm: TermMap, alias: str) -> _Term:
        parts, required = [], []
        if tm.term_kind is TermKind.BLANK_NODE:
            parts.append(self.d.string_literal("_:"))
        for part in parse_template(tm.template or ""):
            if isinstance(part, ColumnRef):
                col = self._col(alias, part.name)
                text = self.d.to_text(col)
                parts.append(self.d.iri_encode(text) if tm.term_kind is TermKind.IRI else text)
                required.append(col)
            elif part:
                parts.append(self.d.string_literal(part))
        if not parts:
            raise CompileError("Empty rr:template")
        return _Term(self.d.concat(parts), tm.term_kind, tuple(required), tm.datatype, tm.language)
