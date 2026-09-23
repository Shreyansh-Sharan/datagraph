"""LLM-backed tasks. Each task builds the prompt, asks the provider for schema-shaped JSON, then
validates the answer against the catalog / ontology before turning it into domain objects.
"""
from __future__ import annotations

import json
from typing import Callable

from ontoforge.catalog import CatalogAdapter
from ontoforge.mapping import AttributeBinding, ClassMapping, MappingSpec, MappingSpecError, RelationMapping
from ontoforge.ontology import DatatypeProperty, ObjectProperty, OntoClass, Ontology, XSD

from . import prompts
from .provider import LLMOutputError, LLMProvider
from .schemas import RELATIONS_SCHEMA, MAPPING_SCHEMA, ONTOLOGY_SCHEMA

TableMeta = dict


def guarded_sampler(fetch: Callable[[str], list[tuple]]) -> Callable[[str], list[tuple]]:
    """Sample rows are a nicety: after the first failure (typically no SELECT grant) stop asking the
    source, so a draft over many tables does not spend a round trip per table on the same error."""
    state = {"ok": True}

    def sample(table: str) -> list[tuple]:
        if not state["ok"]:
            return []
        try:
            return fetch(table)
        except Exception:  # noqa: BLE001 - never fail a draft over samples
            state["ok"] = False
            return []
    return sample


def describe_tables(catalog: CatalogAdapter, tables: list[str] | None = None, schema: str | None = None,
                    sample_rows: Callable[[str], list[tuple]] | None = None, snapshots: dict | None = None,
                    on_progress: Callable[[int, int, str], None] | None = None) -> list[TableMeta]:
    """Catalog metadata in the shape the prompts expect. A version's snapshots win over the live
    catalog when present: they carry the comments users wrote. ``on_progress(i, n, table)`` is
    called before each table so a long run can say where it is."""
    out = []
    snapshots = snapshots or {}
    if tables is not None and schema:   # bare names belong to the given schema, dotted ones are already placed
        tables = [t if "." in t else f"{schema}.{t}" for t in tables]
    names = tables if tables is not None else (list(snapshots) or catalog.list_tables(schema))
    for i, t in enumerate(names):
        if on_progress:
            on_progress(i + 1, len(names), t)
        snap = snapshots.get(t)
        if snap is not None:
            out.append({"table": t, "comment": snap.comment, "columns": snap.columns, "primary_key": snap.primary_key,
                        "foreign_keys": snap.foreign_keys, "samples": [list(r) for r in (sample_rows(t) if sample_rows else [])]})
            continue
        out.append({
            "table": t,
            "comment": catalog.table_comment(t),
            "columns": catalog.column_details(t),
            "primary_key": list(catalog.primary_key(t)),
            "foreign_keys": [{"columns": list(c), "references": r, "referenced_columns": list(rc)} for c, r, rc in catalog.foreign_keys(t)],
            "samples": [list(r) for r in (sample_rows(t) if sample_rows else [])],
        })
    return out


class OntologyDrafter:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    def draft(self, ontology_iri: str, tables: list[TableMeta], description: str = "") -> Ontology:
        user = f"Business domain: {description or '(not given)'}\n\nTables:\n{json.dumps(tables, indent=1, default=str)}"
        data = self.provider.complete_json(prompts.DRAFT_ONTOLOGY, user, ONTOLOGY_SCHEMA)
        return ontology_from_json(ontology_iri, data)


class OntologyAssistant:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    def edit(self, ontology: Ontology, instruction: str) -> Ontology:
        user = f"Instruction: {instruction}\n\nCurrent ontology (Turtle):\n{ontology.to_turtle()}"
        data = self.provider.complete_json(prompts.ASSIST_ONTOLOGY, user, ONTOLOGY_SCHEMA)
        return ontology_from_json(ontology.iri, data)


class MappingSuggester:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    def suggest(self, ontology: Ontology, tables: list[TableMeta], base_iri: str) -> MappingSpec:
        self.skipped: list[str] = []
        user = (f"Ontology:\n{_ontology_summary(ontology)}\n\nTables:\n{json.dumps(tables, indent=1, default=str)}")
        data = self.provider.complete_json(prompts.SUGGEST_MAPPING, user, MAPPING_SCHEMA)
        return mapping_from_json(ontology, tables, base_iri, data, skipped=self.skipped)


# -- JSON -> domain objects, with validation ---------------------------------------

def ontology_from_json(ontology_iri: str, data: dict) -> Ontology:
    o = Ontology(iri=ontology_iri, label=data.get("label"), description=data.get("description"))
    names = {c["name"] for c in data.get("classes", [])}
    for c in data.get("classes", []):
        for p in c.get("parents") or []:
            if p not in names:
                raise LLMOutputError(f"Class {c['name']} has unknown parent {p}")
        o.add_class(OntoClass(_iri(o, c["name"]), c.get("label") or c["name"], c.get("description"),
                              tuple(_iri(o, p) for p in c.get("parents") or [])))
    for p in data.get("datatype_properties", []):
        if p.get("domain") is not None and p["domain"] not in names:
            raise LLMOutputError(f"Property {p['name']} has unknown domain {p['domain']}")
        o.add_datatype_property(DatatypeProperty(_iri(o, p["name"]), p.get("label") or p["name"], p.get("description"),
                                                 _iri(o, p["domain"]) if p.get("domain") else None, XSD + (p.get("range") or "string")))
    for p in data.get("object_properties", []):
        for side in ("domain", "range"):
            if p.get(side) not in names:
                raise LLMOutputError(f"Property {p['name']} has unknown {side} {p.get(side)}")
        o.add_object_property(ObjectProperty(_iri(o, p["name"]), p.get("label") or p["name"], p.get("description"),
                                             _iri(o, p["domain"]), _iri(o, p["range"])))
    return o


def mapping_from_json(ontology: Ontology, tables: list[TableMeta], base_iri: str, data: dict, skipped: list[str] | None = None) -> MappingSpec:
    """The model's answer as a spec. Entries naming a class, property, table or column that does not
    exist are skipped and listed in ``skipped`` (one slip must not void sixty good bindings); only an
    answer with nothing usable is an error."""
    skipped = skipped if skipped is not None else []
    columns = {t["table"].lower(): {c["name"].lower(): c["name"] for c in t["columns"]} for t in tables}
    table_names = {t["table"].lower(): t["table"] for t in tables} | {t["table"].split(".")[-1].lower(): t["table"] for t in tables}
    classes_by_name = {ontology.local_name(iri).lower(): iri for iri in ontology.classes} | {iri.lower(): iri for iri in ontology.classes} \
        | {(c.label or "").lower(): iri for iri, c in ontology.classes.items() if c.label}
    props_by_name = {ontology.local_name(p.iri).lower(): p.iri for p in ontology.all_properties()} | \
                    {p.iri.lower(): p.iri for p in ontology.all_properties()}

    def cls(name: str) -> str:
        if name.lower() not in classes_by_name:
            raise LLMOutputError(f"Unknown class {name}")
        return classes_by_name[name.lower()]

    def prop(name: str) -> str:
        if name.lower() not in props_by_name:
            raise LLMOutputError(f"Unknown property {name}")
        return props_by_name[name.lower()]

    def table(name: str) -> str:
        if name.lower() not in table_names:
            raise LLMOutputError(f"Unknown table {name}")
        return table_names[name.lower()]

    def cols(tname: str, names: list[str] | None, what: str) -> tuple[str, ...]:
        out = []
        for n in names or []:
            if n.lower() not in columns[tname.lower()]:
                raise LLMOutputError(f"Unknown column {n} in table {tname} ({what})")
            out.append(columns[tname.lower()][n.lower()])
        return tuple(out)

    class_mappings = []
    for c in data.get("classes", []):
        try:
            t = table(c["table"])
            class_iri = cls(c["class"])
            keys = cols(t, c.get("key_columns"), "key")
        except (LLMOutputError, KeyError) as exc:
            skipped.append(f"class {c.get('class', '?')}: {exc}")
            continue
        attributes = []
        for a in c.get("attributes", []):
            try:
                attributes.append(AttributeBinding(prop(a["property"]), cols(t, [a["column"]], "attribute")[0]))
            except (LLMOutputError, KeyError) as exc:
                skipped.append(f"{c['class']}.{a.get('property', '?')}: {exc}")
        class_mappings.append(ClassMapping(class_iri, table=t, key_columns=keys, iri_template=c.get("iri_template"), attributes=tuple(attributes)))
    if not class_mappings:
        raise LLMOutputError("The suggestion contained nothing usable: " + ("; ".join(skipped[:3]) if skipped else "no classes"))
    by_class = {m.class_iri: m for m in class_mappings}
    relations = []
    for r in data.get("relations", []):
        try:
            src, tgt = cls(r["source_class"]), cls(r["target_class"])
            if src not in by_class or tgt not in by_class:
                raise LLMOutputError("references an unmapped class")
            link = table(r["table"]) if r.get("table") else None
            rel_table = link or by_class[src].table
            relations.append(RelationMapping(prop(r["property"]), src, tgt,
                                             source_key=cols(rel_table, r.get("source_key"), "source_key") or None,
                                             target_key=cols(rel_table, r.get("target_key"), "target_key") or None, table=link))
        except (LLMOutputError, KeyError) as exc:
            skipped.append(f"relation {r.get('property', '?')}: {exc}")
    # Compile piece by piece: a class or relation the compiler rejects is dropped and reported, the rest stays.
    def compiles(classes, rels) -> str | None:
        try:
            MappingSpec(base_iri=base_iri, classes=tuple(classes), relations=tuple(rels)).to_r2rml()
            return None
        except MappingSpecError as exc:
            return str(exc)
    kept_classes = []
    for c in class_mappings:
        err = compiles([c], [])
        if err:
            skipped.append(f"class {ontology.local_name(c.class_iri)}: {err}")
        else:
            kept_classes.append(c)
    if not kept_classes:
        raise LLMOutputError("The suggestion contained nothing usable: " + ("; ".join(skipped[:3]) if skipped else "no classes"))
    kept_relations = []
    for r in relations:
        err = compiles(kept_classes, kept_relations + [r])
        if err:
            skipped.append(f"relation {ontology.local_name(r.property_iri)}: {err}")
        else:
            kept_relations.append(r)
    return MappingSpec(base_iri=base_iri, classes=tuple(kept_classes), relations=tuple(kept_relations))


def _iri(o: Ontology, name: str) -> str:
    return name if name.startswith(("http://", "https://", "urn:")) else f"{o.iri}#{name}"


def _ontology_summary(o: Ontology) -> str:
    lines = []
    for c in o.classes.values():
        lines.append(f"class {o.local_name(c.iri)}" + (f" (parents: {', '.join(o.local_name(p) for p in c.parents)})" if c.parents else ""))
        for p in o.properties_of(c.iri):
            kind = "attribute" if isinstance(p, DatatypeProperty) else "relationship"
            lines.append(f"  {kind} {o.local_name(p.iri)} -> {o.local_name(p.range) if p.range else '?'}")
    return "\n".join(lines)


class RelationSuggester:
    """Fills the relationships a class mapping leaves open, cheapest evidence first: a foreign key the
    catalog declares, then a source column named like the target's key, then the model, a dozen
    relationships per call with only the two tables involved (never the whole catalog)."""

    def __init__(self, provider: LLMProvider | None, batch: int = 12) -> None:
        self.provider, self.batch = provider, batch
        self.report: dict[str, list[str]] = {"declared": [], "by_name": [], "ai": [], "skipped": [], "unmappable": []}

    def suggest(self, ontology: Ontology, spec: MappingSpec, tables: list[TableMeta], on_progress=None) -> MappingSpec:
        self.report = {"declared": [], "by_name": [], "ai": [], "skipped": [], "unmappable": []}
        local = ontology.local_name
        by_class = {c.class_iri: c for c in spec.classes if c.table}
        metas = {t["table"].lower(): t for t in tables} | {t["table"].split(".")[-1].lower(): t for t in tables}
        meta_of = lambda table: metas.get(table.lower()) or metas.get(table.split(".")[-1].lower())
        cols_of = lambda meta: {c["name"].lower(): c["name"] for c in meta["columns"]} if meta else {}
        existing = {(r.property_iri, r.source_class) for r in spec.relations}
        relations = list(spec.relations)

        def compiles(rel: RelationMapping) -> str | None:
            try:
                MappingSpec(spec.base_iri, spec.classes, tuple(relations) + (rel,)).to_r2rml()
                return None
            except MappingSpecError as exc:
                return str(exc)

        def accept(rel: RelationMapping, bucket: str) -> bool:
            err = compiles(rel)
            if err:
                self.report["skipped"].append(f"{local(rel.property_iri)}: {err}")
                return False
            relations.append(rel)
            existing.add((rel.property_iri, rel.source_class))
            self.report[bucket].append(local(rel.property_iri))
            return True

        # what is still open, and mappable in principle (both ends have a table)
        open_rels: list[tuple[ObjectProperty, str, str]] = []
        for p in ontology.object_properties.values():
            for d in (p.domains or ((p.domain,) if p.domain else ())):
                if not p.range or (p.iri, d) in existing:
                    continue
                if d in by_class and p.range in by_class:
                    open_rels.append((p, d, p.range))
                else:
                    self.report["unmappable"].append(f"{local(p.iri)} ({'source' if d not in by_class else 'target'} class has no table)")
        # 1. declared foreign keys, 2. a column named like the target's key
        ask: list[tuple[ObjectProperty, str, str]] = []
        for p, d, t in open_rels:
            src, tgt = by_class[d], by_class[t]
            src_meta, tgt_meta = meta_of(src.table), meta_of(tgt.table)
            src_cols = cols_of(src_meta)
            done = False
            for fk in (src_meta or {}).get("foreign_keys") or []:
                ref = str(fk.get("references") or "").split(".")[-1].lower()
                if ref == tgt.table.split(".")[-1].lower() and len(fk.get("columns") or []) == len(tgt.key_columns):
                    done = accept(RelationMapping(p.iri, d, t, source_key=src.key_columns, target_key=tuple(fk["columns"])), "declared")
                    break
            if not done and len(tgt.key_columns) == 1:
                name = tgt.key_columns[0].lower()
                if name in src_cols and not (d == t and src_cols[name] in src.key_columns):
                    done = accept(RelationMapping(p.iri, d, t, source_key=src.key_columns, target_key=(src_cols[name],)), "by_name")
            if not done and d != t and len(src.key_columns) == 1:   # parent -> child: the child's table carries the parent's key
                tgt_cols = cols_of(tgt_meta)
                name = src.key_columns[0].lower()
                if name in tgt_cols and (tgt_cols[name] not in tgt.key_columns or len(tgt.key_columns) > 1):
                    done = accept(RelationMapping(p.iri, d, t, source_key=(tgt_cols[name],), target_key=tgt.key_columns, table=tgt.table), "by_name")
            if not done:
                ask.append((p, d, t))
        # 3. the model, a few relationships at a time with only the tables they involve
        if ask and self.provider is None:
            self.report["unmappable"] += [f"{local(p.iri)} (needs the AI provider)" for p, _, _ in ask]
            return MappingSpec(spec.base_iri, spec.classes, tuple(relations))
        for i in range(0, len(ask), self.batch):
            chunk = ask[i:i + self.batch]
            if on_progress:
                on_progress(f"Asking the AI provider about relationships {i + 1}-{min(i + self.batch, len(ask))} of {len(ask)}")
            items, involved = [], {}
            for p, d, t in chunk:
                src, tgt = by_class[d], by_class[t]
                for m in (meta_of(src.table), meta_of(tgt.table)):
                    if m:
                        involved[m["table"]] = {"table": m["table"], "columns": [c["name"] for c in m["columns"]], "primary_key": m.get("primary_key") or []}
                items.append({"property": local(p.iri), "source_class": local(d), "source_table": src.table, "source_key": list(src.key_columns),
                              "target_class": local(t), "target_table": tgt.table, "target_key": list(tgt.key_columns)})
            link_candidates = [{"table": m["table"], "columns": [c["name"] for c in m["columns"]]} for m in tables if m["table"] not in involved][:40]
            user = f"Relationships:\n{json.dumps(items, indent=1)}\n\nTables involved:\n{json.dumps(list(involved.values()), indent=1)}\n\nOther tables that could be link tables:\n{json.dumps(link_candidates, indent=1)}"
            try:
                data = self.provider.complete_json(prompts.SUGGEST_RELATIONS, user, RELATIONS_SCHEMA)
            except LLMOutputError as exc:
                self.report["skipped"] += [f"{local(p.iri)}: the AI provider gave no usable answer ({exc})" for p, _, _ in chunk]
                continue
            answers = {(a.get("property", ""), a.get("source_class", "")): a for a in data.get("relations", [])}
            for p, d, t in chunk:
                a = answers.get((local(p.iri), local(d)))
                src, tgt = by_class[d], by_class[t]
                if not a or not (a.get("column") or a.get("link_table")):
                    self.report["unmappable"].append(f"{local(p.iri)} (no foreign key or link table found)")
                    continue
                if a.get("column"):
                    src_cols = cols_of(meta_of(src.table))
                    col = src_cols.get(str(a["column"]).lower())
                    if not col:
                        self.report["skipped"].append(f"{local(p.iri)}: unknown column {a['column']} in table {src.table}")
                        continue
                    accept(RelationMapping(p.iri, d, t, source_key=src.key_columns, target_key=(col,)), "ai")
                    continue
                link = meta_of(str(a["link_table"]))
                lcols = cols_of(link)
                sc, tc = lcols.get(str(a.get("link_source_column") or "").lower()), lcols.get(str(a.get("link_target_column") or "").lower())
                if not link or not sc or not tc:
                    self.report["skipped"].append(f"{local(p.iri)}: link table {a.get('link_table')} or its columns {a.get('link_source_column')}/{a.get('link_target_column')} do not exist")
                    continue
                accept(RelationMapping(p.iri, d, t, source_key=(sc,), target_key=(tc,), table=link["table"]), "ai")
        return MappingSpec(spec.base_iri, spec.classes, tuple(relations))
