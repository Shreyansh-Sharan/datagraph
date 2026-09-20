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


class AutodraftError(ValueError):
    pass


@dataclass(frozen=True)
class InferredKeys:
    primary_key: tuple[str, ...]
    foreign_keys: list[tuple[tuple[str, ...], str, tuple[str, ...]]]


_PREFIXES = ("dim_", "fact_", "silver_", "gold_", "bronze_", "stg_", "tbl_", "t_")


def _stripped(table: str) -> str:
    name = table.rsplit(".", 1)[-1].lower()
    for pre in _PREFIXES:
        if name.startswith(pre) and len(name) > len(pre):
            return name[len(pre):]
    return name


_KEY_SUFFIX = re.compile(r"(_id|_sk|_key|_code|_no|id)$")


def _owns(table: str, column: str) -> bool:
    """Does ``column`` name this table's identity? ``promo_id`` ~ ``dim_promotion``, ``customer_sk`` ~ ``dim_customer``."""
    col = column.lower()
    if not _KEY_SUFFIX.search(col) or col == "id":
        return False
    stem = _KEY_SUFFIX.sub("", col)
    base = _stripped(table)
    return any(stem == cand or _abbreviates(stem, cand) for cand in (base, singular(base)))


def infer_keys(catalog: CatalogAdapter, tables: list[str]) -> dict[str, InferredKeys]:
    """Guess primary and foreign keys from column names when the catalog declares none.

    A column name is the key of at most one table. Assignment order:
      1. a column naming the table itself (``customer_id`` in dim_customer, ``promo_id`` in dim_promotion);
      2. for tables still without a key, the unassigned ``*_id``/``*_sk`` column most referenced by other
         tables (``sku_id`` in dim_product, ``date_id`` in dim_calendar);
      3. a plain ``id``;
      4. a surrogate named after the raw table name (``dim_product_sk``);
      5. otherwise the table's foreign-key columns together (fact tables), or every column.
    Foreign key: any non-key column equal to another table's assigned single-column key.
    """
    columns = {t: list(catalog.column_types(t)) for t in tables}
    refs: dict[str, int] = {}
    for cols in columns.values():
        for c in {x.lower() for x in cols}:
            refs[c] = refs.get(c, 0) + 1
    pks: dict[str, tuple[str, ...]] = {t: () for t in tables}
    assigned: set[str] = set()

    def assign(t: str, col: str) -> None:
        pks[t] = (col,)
        assigned.add(col.lower())

    for t, cols in columns.items():                                   # 1. self-named keys
        own = [c for c in cols if _owns(t, c) and c.lower() not in assigned]
        if own:
            own.sort(key=lambda c: (0 if c.lower().endswith("_sk") else 1, -(refs[c.lower()] - 1)))
            assign(t, own[0])
    for t, cols in columns.items():                                   # 2. most-referenced unassigned id column
        if pks[t]:
            continue
        cands = [c for c in cols if _KEY_SUFFIX.search(c.lower()) and c.lower() != "id" and c.lower() not in assigned and refs[c.lower()] > 1]
        if cands:
            cands.sort(key=lambda c: -refs[c.lower()])
            assign(t, cands[0])
    for t, cols in columns.items():                                   # 3. plain id
        if not pks[t]:
            plain = next((c for c in cols if c.lower() == "id"), None)
            if plain:
                pks[t] = (plain,)
    for t, cols in columns.items():                                   # 4. raw-name surrogate
        if not pks[t]:
            raw = t.rsplit(".", 1)[-1].lower()
            sur = next((c for c in cols if _KEY_SUFFIX.sub("", c.lower()) == raw and c.lower() not in assigned), None)
            if sur:
                assign(t, sur)
    key_owner = {pk[0].lower(): t for t, pk in pks.items() if len(pk) == 1}
    out: dict[str, InferredKeys] = {}
    for t, cols in columns.items():
        fks = [((c,), key_owner[c.lower()], pks[key_owner[c.lower()]]) for c in cols
               if c.lower() in key_owner and key_owner[c.lower()] != t and (not pks[t] or c.lower() != pks[t][0].lower())]
        pk = pks[t] or tuple(c for cols_, _, _ in fks for c in cols_)             # 5. composite of FKs
        out[t] = InferredKeys(pk, fks)
    return out


def draft_from_catalog(catalog: CatalogAdapter, *, ontology_iri: str, base_iri: str,
                       tables: list[str] | None = None, schema: str | None = None, infer: bool = True) -> tuple[Ontology, MappingSpec]:
    tables = tables if tables is not None else catalog.list_tables(schema)
    onto = Ontology(iri=ontology_iri, label=Ontology.local_name(ontology_iri) or "Draft")
    inferred = infer_keys(catalog, tables) if infer else {}
    meta = {}
    for t in tables:
        if not catalog.column_types(t):
            raise AutodraftError(f"Table {t!r} was not found in the catalog or has no columns")
        pk, fks = catalog.primary_key(t), catalog.foreign_keys(t)
        if infer and not pk and not fks and t in inferred:
            pk, fks = inferred[t].primary_key, inferred[t].foreign_keys
        meta[t] = _TableMeta(t, catalog.column_types(t), pk, fks)
    class_iri: dict[str, str] = {}
    for t, m in meta.items():
        if m.is_link_table:
            continue
        iri = onto.mint(singular(_class_stem(t)), capitalize=True)
        if iri in class_iri.values():                       # e.g. dim_promotion vs fact_promotions
            iri = onto.mint(singular(t.rsplit(".", 1)[-1]), capitalize=True)
        n = 2
        while iri in class_iri.values():
            iri = onto.mint(singular(t.rsplit(".", 1)[-1]) + str(n), capitalize=True)
            n += 1
        class_iri[t] = iri
    classes: list[ClassMapping] = []
    relations: list[RelationMapping] = []

    for t, m in meta.items():
        if m.is_link_table:
            continue
        onto.add_class(OntoClass(class_iri[t], label=humanize(onto.local_name(class_iri[t]))))
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
    return _stripped(table)


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
