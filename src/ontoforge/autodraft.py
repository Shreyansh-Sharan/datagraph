"""Draft an ontology and a mapping spec from catalog metadata alone.

Heuristics (no LLM): a table is a class; a column is a datatype property; a foreign key is an
object property; a table made only of foreign keys is a many-to-many relation. Names are
derived from identifiers (``employee_skills`` -> ``EmployeeSkill``). The result is a starting
point for a human or an LLM to refine, and it is buildable as-is.
"""
from __future__ import annotations

import re

from ontoforge.catalog import CatalogAdapter
from ontoforge.dialects import PostgresDialect, XSD
from ontoforge.mapping import AttributeBinding, ClassMapping, MappingSpec, RelationMapping
from ontoforge.ontology import DatatypeProperty, ObjectProperty, OntoClass, Ontology


def draft_from_catalog(catalog: CatalogAdapter, *, ontology_iri: str, base_iri: str,
                       tables: list[str] | None = None, schema: str | None = None) -> tuple[Ontology, MappingSpec]:
    tables = tables if tables is not None else catalog.list_tables(schema)
    onto = Ontology(iri=ontology_iri, label=Ontology.local_name(ontology_iri) or "Draft")
    meta = {t: _TableMeta(t, catalog.column_types(t), catalog.primary_key(t), catalog.foreign_keys(t)) for t in tables}
    class_iri = {t: onto.mint(singular(t), capitalize=True) for t, m in meta.items() if not m.is_link_table}
    classes: list[ClassMapping] = []
    relations: list[RelationMapping] = []

    for t, m in meta.items():
        if m.is_link_table:
            continue
        onto.add_class(OntoClass(class_iri[t], label=humanize(singular(t))))
        attributes = []
        for col, sql_type in m.columns.items():
            if col in m.fk_columns:
                continue
            prop = _datatype_property(onto, class_iri[t], col, sql_type)
            attributes.append(AttributeBinding(prop.iri, col))
        classes.append(ClassMapping(class_iri[t], table=t, key_columns=m.key, attributes=tuple(attributes)))
        for cols, ref, _ in m.fks:
            if ref not in class_iri:
                continue
            name = _relation_name(cols, ref, m.fks)
            prop = onto.add_object_property(ObjectProperty(onto.mint(name), label=humanize(name),
                                                           domain=class_iri[t], range=class_iri[ref]))
            relations.append(RelationMapping(prop.iri, class_iri[t], class_iri[ref], target_key=cols))

    for t, m in meta.items():
        if not m.is_link_table:
            continue
        (scols, sref, _), (tcols, tref, _) = m.fks
        if sref not in class_iri or tref not in class_iri:
            continue
        name = camel(singular(t))
        prop = onto.add_object_property(ObjectProperty(onto.mint(name), label=humanize(name), domain=class_iri[sref], range=class_iri[tref]))
        relations.append(RelationMapping(prop.iri, class_iri[sref], class_iri[tref], table=t, source_key=scols, target_key=tcols))

    return onto, MappingSpec(base_iri=base_iri, classes=tuple(classes), relations=tuple(relations))


class _TableMeta:
    def __init__(self, name: str, columns: dict[str, str], pk: tuple[str, ...], fks: list) -> None:
        self.name, self.columns, self.fks = name, columns, fks
        self.key = pk or tuple(columns)
        self.fk_columns = {c for cols, *_ in fks for c in cols}
        self.is_link_table = len(fks) == 2 and set(columns) == self.fk_columns


def _datatype_property(onto: Ontology, domain: str, column: str, sql_type: str) -> DatatypeProperty:
    iri = onto.mint(camel(column))
    existing = onto.datatype_properties.get(iri)
    if existing and existing.domain != domain:
        iri = onto.mint(camel(f"{Ontology.local_name(domain)}_{column}"))
    xsd = PostgresDialect().xsd_for_sql_type(sql_type) or XSD + "string"
    return onto.add_datatype_property(DatatypeProperty(iri, label=humanize(column), domain=domain, range=xsd))


def _relation_name(cols: tuple[str, ...], ref_table: str, all_fks: list) -> str:
    target = singular(ref_table)
    stem = re.sub(r"(_?id|_?no|_?key|_?code)$", "", cols[0].lower()) or cols[0].lower()
    same_target = [f for f in all_fks if f[1] == ref_table]
    if _abbreviates(stem, target) and len(same_target) == 1:
        return camel(target)
    return camel(stem)


def _abbreviates(short: str, long: str) -> bool:
    """True when ``short`` is ``long`` with letters dropped (``dept`` ~ ``department``, ``emp`` ~ ``employee``)."""
    if not short or short[0] != long[:1]:
        return False
    it = iter(long)
    return all(ch in it for ch in short)


def singular(name: str) -> str:
    n = name.lower()
    if n.endswith("ies"):
        return n[:-3] + "y"
    if n.endswith(("ses", "xes", "shes", "ches")):
        return n[:-2]
    if n.endswith("s") and not n.endswith("ss"):
        return n[:-1]
    return n


def camel(identifier: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", identifier)
    return words[0].lower() + "".join(w[:1].upper() + w[1:] for w in words[1:]) if words else identifier


def humanize(identifier: str) -> str:
    return " ".join(re.findall(r"[A-Za-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", identifier))).lower()
