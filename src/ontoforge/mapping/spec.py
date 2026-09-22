"""The mapping spec: how a UI or an LLM says "this class is that table".

It is compiled to standard R2RML (``to_r2rml``), which is what the SQL compiler consumes.
Subject IRIs follow the convention ``{base_iri}{ClassLocalName}/{key1}-{key2}`` unless a class
supplies its own ``iri_template``. Relations are expressed without joins: the target IRI is
rebuilt from foreign-key columns on the relation's own logical table, which compiles to a
plain projection instead of a join.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from urllib.parse import quote, unquote

from ontoforge.compiler.template import ColumnRef, parse_template
from ontoforge.ontology.model import Ontology
from ontoforge.r2rml.model import LogicalTable, Mapping, PredicateObjectMap, TermKind, TermMap, TriplesMap


class MappingSpecError(ValueError):
    pass


DIRECTIONS = ("forward", "reverse", "bidirectional")


@dataclass(frozen=True)
class AttributeBinding:
    property_iri: str
    column: str
    datatype: str | None = None
    language: str | None = None


@dataclass(frozen=True)
class ClassMapping:
    class_iri: str
    table: str | None = None
    sql_query: str | None = None
    key_columns: tuple[str, ...] = ()
    iri_template: str | None = None
    attributes: tuple[AttributeBinding, ...] = ()
    excluded: tuple[str, ...] = ()   # property IRIs deliberately left unmapped (don't count as gaps)

    def __post_init__(self) -> None:
        object.__setattr__(self, "excluded", tuple(sorted(set(self.excluded))))


@dataclass(frozen=True)
class RelationMapping:
    property_iri: str
    source_class: str
    target_class: str
    source_key: tuple[str, ...] | None = None  # columns in the relation's logical table identifying the source row (ignored on the source's own table: its key)
    target_key: tuple[str, ...] | None = None  # ... and the target row
    table: str | None = None                   # defaults to the source class's logical table
    sql_query: str | None = None
    direction: str = "forward"                 # forward: source->target · reverse: target->source · bidirectional: both

    def __post_init__(self) -> None:
        if self.direction not in DIRECTIONS:
            raise MappingSpecError(f"{self.property_iri}: direction must be one of {DIRECTIONS}")


@dataclass(frozen=True)
class MappingSpec:
    base_iri: str
    classes: tuple[ClassMapping, ...] = ()
    relations: tuple[RelationMapping, ...] = ()

    # -- compile -------------------------------------------------------------

    def to_r2rml(self) -> Mapping:
        by_class = {c.class_iri: c for c in self.classes}
        mapping = Mapping()
        for c in self.classes:
            if not c.key_columns and not c.iri_template:
                raise MappingSpecError(f"{c.class_iri}: key_columns or iri_template is required")
            poms = tuple(
                PredicateObjectMap((TermMap(TermKind.IRI, constant=a.property_iri),),
                                   (TermMap(TermKind.LITERAL, column=a.column, datatype=a.datatype, language=a.language),))
                for a in c.attributes)
            iri = f"{self.base_iri}mapping/{Ontology.local_name(c.class_iri)}"
            mapping.triples_maps[iri] = TriplesMap(iri, self._logical_table(c.table, c.sql_query, c.class_iri),
                                                   TermMap(TermKind.IRI, template=self.subject_template(c)),
                                                   classes=(c.class_iri,), predicate_object_maps=poms)
        for i, r in enumerate(self.relations):
            src, tgt = by_class.get(r.source_class), by_class.get(r.target_class)
            if src is None:
                raise MappingSpecError(f"{r.property_iri}: source class {r.source_class} has no mapping")
            if tgt is None:
                raise MappingSpecError(f"{r.property_iri}: target class {r.target_class} has no mapping")
            own_table = r.table is None and r.sql_query is None
            table, query = (src.table, src.sql_query) if own_table else (r.table, r.sql_query)
            # On the source class's own table every row is a source instance, so the subject is the class
            # key whatever source_key says (the AI and older UIs put the FK column there); the FK identifies the target.
            source_key = self._key_columns(src) if own_table else r.source_key
            target_key = r.target_key or (self._key_columns(tgt) if (not own_table and r.table == tgt.table) else None)
            if source_key is None or target_key is None:
                raise MappingSpecError(f"{r.property_iri}: source_key and target_key are required on a link table")
            subject = self._rebind(self.subject_template(src), self._key_columns(src), source_key, r.property_iri)
            obj = self._rebind(self.subject_template(tgt), self._key_columns(tgt), target_key, r.property_iri)
            pairs = {"forward": [(subject, obj)], "reverse": [(obj, subject)], "bidirectional": [(subject, obj), (obj, subject)]}[r.direction]
            for j, (s_tpl, o_tpl) in enumerate(pairs):
                iri = f"{self.base_iri}mapping/rel/{Ontology.local_name(r.property_iri)}/{i}" + ("" if j == 0 else "/rev")
                mapping.triples_maps[iri] = TriplesMap(
                    iri, self._logical_table(table, query, r.property_iri), TermMap(TermKind.IRI, template=s_tpl),
                    predicate_object_maps=(PredicateObjectMap((TermMap(TermKind.IRI, constant=r.property_iri),),
                                                              (TermMap(TermKind.IRI, template=o_tpl),)),))
        return mapping

    def key_values_from_iri(self, class_iri: str, iri: str) -> dict[str, str] | None:
        """Invert a class's subject template: entity IRI -> {key column: value}, or None if no match."""
        cm = next((c for c in self.classes if c.class_iri == class_iri), None)
        if cm is None:
            return None
        pattern, names = "^", []
        for part in parse_template(self.subject_template(cm)):
            if isinstance(part, ColumnRef):
                pattern += "(.+?)"
                names.append(part.name)
            else:
                pattern += re.escape(part)
        m = re.match(pattern + "$", iri)
        return {n: unquote(v) for n, v in zip(names, m.groups())} if m else None

    def iri_for(self, c: ClassMapping, key_values: list[str] | tuple[str, ...]) -> str:
        """Fill a class's subject template with key values (positional), percent-encoding them like the compiler does."""
        cols = self._key_columns(c)
        if len(cols) != len(key_values):
            raise MappingSpecError(f"{c.class_iri}: expected {len(cols)} key value(s), got {len(key_values)}")
        values = dict(zip((k.lower() for k in cols), key_values))
        return "".join(quote(str(values[p.name.lower()]), safe="-._~") if isinstance(p, ColumnRef) else p
                       for p in parse_template(self.subject_template(c)))

    def subject_template(self, c: ClassMapping) -> str:
        if c.iri_template:
            return c.iri_template
        keys = "-".join("{" + k + "}" for k in c.key_columns)
        return f"{self.base_iri}{Ontology.local_name(c.class_iri)}/{keys}"

    @staticmethod
    def _key_columns(c: ClassMapping) -> tuple[str, ...]:
        if c.key_columns:
            return c.key_columns
        return tuple(p.name for p in parse_template(c.iri_template or "") if isinstance(p, ColumnRef))

    @staticmethod
    def _rebind(template: str, from_cols: tuple[str, ...], to_cols: tuple[str, ...], ctx: str) -> str:
        if len(from_cols) != len(to_cols):
            raise MappingSpecError(f"{ctx}: key has {len(to_cols)} column(s) but the class key has {len(from_cols)}")
        ren = {f.lower(): t for f, t in zip(from_cols, to_cols)}
        out = []
        for part in parse_template(template):
            if isinstance(part, ColumnRef):
                if part.name.lower() not in ren:
                    raise MappingSpecError(f"{ctx}: template column {part.name} is not a key column")
                out.append("{" + ren[part.name.lower()] + "}")
            else:
                out.append(part.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}"))
        return "".join(out)

    @staticmethod
    def _logical_table(table: str | None, query: str | None, ctx: str) -> LogicalTable:
        if (table is None) == (query is None):
            raise MappingSpecError(f"{ctx}: exactly one of table / sql_query is required")
        return LogicalTable(table_name=table, sql_query=query)

    # -- (de)serialisation ---------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> MappingSpec:
        return cls(
            base_iri=d["base_iri"],
            classes=tuple(ClassMapping(c["class_iri"], c.get("table"), c.get("sql_query"), tuple(c.get("key_columns", ())),
                                       c.get("iri_template"),
                                       tuple(AttributeBinding(a["property_iri"], a["column"], a.get("datatype"), a.get("language"))
                                             for a in c.get("attributes", ())), tuple(c.get("excluded", ()))) for c in d.get("classes", ())),
            relations=tuple(RelationMapping(r["property_iri"], r["source_class"], r["target_class"],
                                            _opt_tuple(r.get("source_key")), _opt_tuple(r.get("target_key")),
                                            r.get("table"), r.get("sql_query"), r.get("direction", "forward")) for r in d.get("relations", ())))


def _opt_tuple(v) -> tuple[str, ...] | None:
    return None if v is None else tuple(v)
