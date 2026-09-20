"""Draft an ontology and a mapping spec from catalog metadata alone.

Heuristics (no LLM): a table is a class; a column is a datatype property; a foreign key is an
object property; a table made only of foreign keys is a many-to-many relation. Names are
derived from identifiers (``employee_skills`` -> ``EmployeeSkill``). The result is a starting
point for a human or an LLM to refine, and it is buildable as-is.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ontoforge.catalog import CatalogAdapter
from ontoforge.dialects import PostgresDialect, XSD
from ontoforge.mapping import AttributeBinding, ClassMapping, MappingSpec, RelationMapping
from ontoforge.ontology import DatatypeProperty, ObjectProperty, OntoClass, Ontology


@dataclass(frozen=True)
class InferredKeys:
    primary_key: tuple[str, ...]
    foreign_keys: list[tuple[tuple[str, ...], str, tuple[str, ...]]]


_PREFIXES = ("dim_", "fact_", "silver_", "gold_", "bronze_", "stg_", "tbl_", "t_")


def _stems(table: str) -> list[str]:
    name = table.rsplit(".", 1)[-1].lower()
    stripped = name
    for pre in _PREFIXES:
        if stripped.startswith(pre):
            stripped = stripped[len(pre):]
            break
    out = []
    for cand in (stripped, singular(stripped), name, singular(name)):
        if cand and cand not in out:
            out.append(cand)
    return out


def _primary_key_by_naming(table: str, columns: list[str]) -> tuple[str, ...]:
    lower = {c.lower(): c for c in columns}
    for stem in _stems(table):
        for pattern in (f"{stem}_sk", f"{stem}_id", f"{stem}id", f"{stem}_key", f"{stem}_code", f"{stem}_no"):
            if pattern in lower:
                return (lower[pattern],)
    if "id" in lower:
        return (lower["id"],)
    return ()


def infer_keys(catalog: CatalogAdapter, tables: list[str]) -> dict[str, InferredKeys]:
    """Guess primary and foreign keys from column names when the catalog declares none.

    PK: ``<stem>_sk`` / ``<stem>_id`` / ``<stem>id`` / ``id`` (stem = table name minus dim_/fact_/... prefixes,
    singular or plural). FK: a non-key column whose name equals another table's single-column PK.
    Tables without a name-based PK use the set of their FK columns (typical for fact tables).
    """
    columns = {t: list(catalog.column_types(t)) for t in tables}
    pks = {t: _primary_key_by_naming(t, cols) for t, cols in columns.items()}
    by_pk_name: dict[str, list[str]] = {}
    for t, pk in pks.items():
        if len(pk) == 1:
            by_pk_name.setdefault(pk[0].lower(), []).append(t)
    out: dict[str, InferredKeys] = {}
    for t, cols in columns.items():
        fks = []
        for c in cols:
            if pks[t] and c.lower() == pks[t][0].lower():
                continue
            for ref in by_pk_name.get(c.lower(), []):
                if ref != t:
                    fks.append(((c,), ref, (pks[ref][0],)))
        pk = pks[t] or tuple(c for cols_, _, _ in fks for c in cols_)
        out[t] = InferredKeys(pk, fks)
    return out


def draft_from_catalog(catalog: CatalogAdapter, *, ontology_iri: str, base_iri: str,
                       tables: list[str] | None = None, schema: str | None = None, infer: bool = True) -> tuple[Ontology, MappingSpec]:
    tables = tables if tables is not None else catalog.list_tables(schema)
    onto = Ontology(iri=ontology_iri, label=Ontology.local_name(ontology_iri) or "Draft")
    inferred = infer_keys(catalog, tables) if infer else {}
    meta = {}
    for t in tables:
        pk, fks = catalog.primary_key(t), catalog.foreign_keys(t)
        if infer and not pk and not fks and t in inferred:
            pk, fks = inferred[t].primary_key, inferred[t].foreign_keys
        meta[t] = _TableMeta(t, catalog.column_types(t), pk, fks)
    class_iri = {t: onto.mint(singular(_class_stem(t)), capitalize=True) for t, m in meta.items() if not m.is_link_table}
    classes: list[ClassMapping] = []
    relations: list[RelationMapping] = []

    for t, m in meta.items():
        if m.is_link_table:
            continue
        onto.add_class(OntoClass(class_iri[t], label=humanize(singular(_class_stem(t)))))
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
            iri = onto.mint(name)
            if iri in onto.datatype_properties or iri in onto.classes:   # never reuse an attribute's IRI
                name, iri = name + "Ref", onto.mint(name + "Ref")
            prop = onto.add_object_property(ObjectProperty(iri, label=humanize(name),
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
    stem = re.sub(r"(_?id|_?sk|_?no|_?key|_?code)$", "", cols[0].lower()) or cols[0].lower()
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


def _class_stem(table: str) -> str:
    name = table.rsplit(".", 1)[-1]
    for pre in _PREFIXES:
        if name.lower().startswith(pre) and len(name) > len(pre):
            return name[len(pre):]
    return name


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
