from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
import re
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import PlainTextResponse
from graphql import graphql_sync, print_schema
from pydantic import BaseModel, Field

from ontoforge.auth import Principal, Role
from ontoforge.auth.fastapi import admin, builder, reviewer, viewer
from ontoforge.attachments import AttachmentError, Attachments
from ontoforge.autodraft import draft_from_catalog
from ontoforge.bundle import export_bundle, import_bundle
from ontoforge.cohorts import Cohort, CohortError
from ontoforge.compiler import compile_mapping
from ontoforge.dialects import DIALECTS
from ontoforge.graphql import build_schema
from ontoforge.llm import LLMUnavailable, MappingSuggester, OntologyAssistant, OntologyDrafter, describe_tables
from ontoforge.mapping import ClassMapping, MappingSpec, mapping_status
from ontoforge.ontology import INDUSTRY_ONTOLOGIES, Ontology, merge_ontologies
from ontoforge.r2rml import serialize_r2rml
from ontoforge.reasoning import generate_shapes
from ontoforge.quality import ConstraintSet, QualityEngine, QualityError
from ontoforge.rules import Rule, RuleEngine, RuleError, RuleSet
from ontoforge.registry import Domain, DomainVersion, LifecycleError, NotFound, Status

router = APIRouter(dependencies=[Depends(viewer)])   # every route needs an authenticated caller
open_router = APIRouter()                                # /health only


def _st(request: Request):
    return request.app.state


def _version_json(v: DomainVersion) -> dict:
    d = asdict(v)
    d["has_ontology"], d["has_mapping"], d["has_r2rml"] = bool(v.ontology_ttl), bool(v.mapping), bool(v.r2rml_ttl)
    d["rule_count"] = len((v.rules or {}).get("rules", []))
    d["constraint_count"] = len((v.quality or {}).get("constraints", []))
    for k in ("ontology_ttl", "mapping", "r2rml_ttl", "rules", "quality"):
        d.pop(k)
    return d


# -- models ----------------------------------------------------------------------

class DomainIn(BaseModel):
    name: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_\-]+$")
    description: str | None = None
    base_iri: str
    review_quorum: int = 1


class DomainUpdateIn(BaseModel):
    description: str | None = None
    review_quorum: int | None = Field(default=None, ge=0)
    base_iri: str | None = None
    connection_id: UUID | None = None
    ai_connection_id: UUID | None = None
    default_catalog: str | None = None
    default_schema: str | None = None
    materialization: str | None = None
    target_schema: str | None = None


class ConnectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str
    config: dict = Field(default_factory=dict)
    secret: str | None = None


class ConnectionUpdateIn(BaseModel):
    name: str | None = None
    config: dict | None = None
    secret: str | None = None      # omitted: keep the stored secret


class ConnectionTestIn(BaseModel):
    kind: str
    config: dict = Field(default_factory=dict)
    secret: str | None = None


class OntologyIn(BaseModel):
    turtle: str


class OntologyImportIn(BaseModel):
    data: str | None = None
    url: str | None = None
    source: str | None = None            # a key of INDUSTRY_ONTOLOGIES
    format: str = "turtle"               # turtle | xml | json-ld | n3 | nt
    mode: str = "merge"                  # merge | replace


class TransitionIn(BaseModel):
    to: Status


class ReviewIn(BaseModel):
    approved: bool
    comment: str | None = None


class LeaseIn(BaseModel):
    ttl_seconds: int = 900
    force: bool = False


class GraphQLIn(BaseModel):
    query: str
    variables: dict | None = None


class DraftOntologyIn(BaseModel):
    ontology_iri: str
    description: str = ""
    tables: list[str] | None = None
    schema_name: str | None = None


class SuggestMappingIn(BaseModel):
    tables: list[str] | None = None
    schema_name: str | None = None


class AssistIn(BaseModel):
    instruction: str


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    text: str
    mode: str = "materialize"
    enabled: bool = True


class RulesIn(BaseModel):
    rules: list[RuleIn]


class CommunitiesIn(BaseModel):
    algorithm: str = "louvain"
    resolution: float = 1.0
    seed: int = 42
    persist: bool = False


class CentralitiesIn(BaseModel):
    top_n: int = Field(default=20, ge=1, le=500)


class ExcludeIn(BaseModel):
    class_iri: str
    property_iri: str
    excluded: bool = True


class TestSqlIn(BaseModel):
    sql: str
    limit: int = Field(default=20, ge=1, le=500)


class VersionCommentIn(BaseModel):
    body: str = Field(min_length=1)


class ActiveIn(BaseModel):
    version_id: UUID | None = None


class McpPolicyIn(BaseModel):
    exposed: bool = True
    disabled_tools: list[str] = Field(default_factory=list)


class MetadataImportIn(BaseModel):
    tables: list[str]
    schema_name: str | None = None


class CommentIn(BaseModel):
    comment: str | None


class AutodraftIn(BaseModel):
    ontology_iri: str
    tables: list[str] | None = None
    schema_name: str | None = None
    infer_keys: bool = True


# -- identity & administration ---------------------------------------------------

class RoleIn(BaseModel):
    role: Role


class ApiKeyIn(BaseModel):
    name: str
    principal: str
    role: Role


@router.get("/me")
def me(me: Principal = Depends(viewer)):
    return {"name": me.name, "role": me.role.value}


@router.get("/admin/principals")
def list_principals(request: Request, me: Principal = Depends(admin)):
    return _st(request).principals.list_roles()


@router.put("/admin/principals/{name}")
def set_principal_role(name: str, body: RoleIn, request: Request, me: Principal = Depends(admin)):
    _st(request).principals.set_role(name, body.role)
    return {"name": name, "role": body.role.value}


@router.delete("/admin/principals/{name}", status_code=204)
def delete_principal(name: str, request: Request, me: Principal = Depends(admin)):
    _st(request).principals.delete(name)
    return Response(status_code=204)


@router.post("/admin/api-keys", status_code=201)
def create_api_key(body: ApiKeyIn, request: Request, me: Principal = Depends(admin)):
    return _st(request).principals.create_api_key(body.name, principal=body.principal, role=body.role)


@router.get("/admin/api-keys")
def list_api_keys(request: Request, me: Principal = Depends(admin)):
    return [{k: v for k, v in asdict(key).items() if k != "secret"} for key in _st(request).principals.list_api_keys()]


@router.delete("/admin/api-keys/{key_id}", status_code=204)
def revoke_api_key(key_id: UUID, request: Request, me: Principal = Depends(admin)):
    _st(request).principals.revoke_api_key(key_id)
    return Response(status_code=204)


# -- health / domains ------------------------------------------------------------

@open_router.get("/", include_in_schema=False)
def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/ui/", status_code=307)


@open_router.get("/auth/config")
def auth_config(request: Request):
    """How clients should identify themselves (no secrets here)."""
    s = _st(request).settings
    return {"mode": s.auth_mode, "header": s.auth_header, "default_role": s.auth_default_role,
            "source": {"kind": s.source_kind, "catalog": s.databricks_catalog if s.source_kind == "databricks" else None}}


@open_router.get("/health")
def health(request: Request):
    with _st(request).db.transaction() as cur:
        cur.execute("SELECT 1")
    return {"status": "ok"}


@router.get("/domains")
def list_domains(request: Request):
    return _st(request).registry.list_domains()


@router.post("/domains", status_code=201)
def create_domain(body: DomainIn, request: Request, me: Principal = Depends(builder)):
    return _st(request).registry.create_domain(body.name, body.description, base_iri=body.base_iri, review_quorum=body.review_quorum)


def _source_facts(st, d: Domain) -> dict:
    """Where a domain's tables come from: its own connection, else the deployment's env source."""
    settings = st.settings
    if d.connection_id:
        c = st.connections.get(str(d.connection_id))
        cfg = c["config"]
        facts = {"kind": c["kind"], "connection": c["name"], "connection_id": c["id"], "catalog": d.default_catalog or cfg.get("catalog"),
                 "schema": d.default_schema or cfg.get("schema"), "host": cfg.get("host") or cfg.get("endpoint"), "last_test": c.get("last_test")}
    else:
        facts = {"kind": settings.source_kind, "connection": None, "connection_id": None,
                 "catalog": d.default_catalog or (settings.databricks_catalog if settings.source_kind == "databricks" else None),
                 "schema": d.default_schema or (settings.databricks_schema if settings.source_kind == "databricks" else None), "host": None, "last_test": None}
    facts.update({"auth_mode": settings.auth_mode, "auth_header": settings.auth_header, "materialization": d.materialization, "target_schema": d.target_schema,
                  "connections_backend": st.connections.source})
    if d.ai_connection_id:
        a = st.connections.get(str(d.ai_connection_id))
        facts["ai"] = {"connection": a["name"], "kind": a["kind"], "deployment": a["config"].get("deployment")}
    else:
        facts["ai"] = {"connection": None, "kind": settings.llm_provider, "deployment": settings.azure_openai_deployment if settings.llm_provider == "azure_openai" else settings.llm_model} if settings.llm_provider != "none" else None
    return facts


@router.get("/domains/cards")
def domain_cards(request: Request):
    """One row per domain for the Home screen: versions, served graph size, last build, source, MCP."""
    st = _st(request)
    out = []
    for d in st.registry.list_domains():
        versions = st.registry.list_versions(d.id)
        latest = max(versions, key=lambda v: v.version) if versions else None
        active = next((v for v in versions if v.id == d.active_version_id), None)
        served = st.registry.served_version(d.id) if versions else None
        build = st.registry.latest_build(served.id) if served else None
        src = _source_facts(st, d)
        out.append({"name": d.name, "description": d.description, "base_iri": d.base_iri, "review_quorum": d.review_quorum,
                    "version_count": len(versions), "active_version": {"version": active.version} if active else None,
                    "latest_version": {"version": latest.version, "status": latest.status.value} if latest else None,
                    "triples": st.store.count(served.id) if served else 0,
                    "last_build": {"status": build.status, "finished_at": build.finished_at, "triple_count": build.triple_count} if build else None,
                    "source": {"kind": src["kind"], "connection": src["connection"], "catalog": src["catalog"], "schema": src["schema"]},
                    "mcp": {"exposed": d.mcp_exposed, "disabled_tools": list(d.mcp_policy.get("disabled_tools", []))}})
    return out


@router.get("/domains/{name}")
def get_domain(name: str, request: Request):
    return _st(request).registry.get_domain(name)


@router.delete("/domains/{name}", status_code=204)
def delete_domain(name: str, request: Request, me: Principal = Depends(admin)):
    reg = _st(request).registry
    reg.delete_domain(reg.get_domain(name).id)
    return Response(status_code=204)


@router.post("/domains/{name}/active")
def set_active(name: str, body: ActiveIn, request: Request, me: Principal = Depends(reviewer)):
    reg = _st(request).registry
    return reg.set_active_version(reg.get_domain(name).id, body.version_id, actor=me.name)


@router.get("/tasks")
def my_tasks(request: Request, me: Principal = Depends(viewer)):
    return _st(request).registry.tasks_for(me.name)


@router.get("/admin/locks")
def admin_locks(request: Request, me: Principal = Depends(admin)):
    return _st(request).registry.list_locks()


@router.delete("/admin/locks/{version_id}", status_code=204)
def admin_force_unlock(version_id: UUID, request: Request, me: Principal = Depends(admin)):
    _st(request).registry.force_release(version_id, actor=me.name)
    return Response(status_code=204)


@router.get("/domains/{name}/mcp-policy")
def get_mcp_policy(name: str, request: Request):
    return _st(request).registry.get_domain(name).mcp_policy


@router.put("/domains/{name}/mcp-policy")
def put_mcp_policy(name: str, body: McpPolicyIn, request: Request, me: Principal = Depends(builder)):
    reg = _st(request).registry
    return reg.set_mcp_policy(reg.get_domain(name).id, body.model_dump()).mcp_policy


@router.get("/domains/{name}/export")
def export_domain(name: str, request: Request, version_id: UUID | None = None,
                  versions: str = Query(default="active", pattern="^(active|latest|all)$")):
    return export_bundle(_st(request).registry, name, version_id, versions)


@router.post("/domains/import", status_code=201)
def import_domain(body: dict, request: Request, me: Principal = Depends(builder),
                  on_conflict: str = Query(default="fail", pattern="^(fail|skip|overwrite|rename)$")):
    result = import_bundle(_st(request).registry, body, actor=me.name, name=body.get("name"), on_conflict=on_conflict)
    return {"domain": result.domain, "imported": result.imported, "skipped": result.skipped,
            "versions": [_version_json(v) for v in result.versions]}


@router.get("/domains/{name}/versions")
def list_versions(name: str, request: Request):
    reg = _st(request).registry
    return [_version_json(v) for v in reg.list_versions(reg.get_domain(name).id)]


@router.post("/domains/{name}/versions", status_code=201)
def create_version(name: str, request: Request, me: Principal = Depends(builder)):
    reg = _st(request).registry
    return _version_json(reg.create_version(reg.get_domain(name).id, actor=me.name))


# -- versions: content -----------------------------------------------------------

@router.get("/versions/{version_id}")
def get_version(version_id: UUID, request: Request):
    return _version_json(_st(request).registry.get_version(version_id))


@router.put("/versions/{version_id}/ontology")
def put_ontology(version_id: UUID, body: OntologyIn, request: Request, me: Principal = Depends(builder)):
    Ontology.from_turtle(body.turtle)  # validate before storing
    return _version_json(_st(request).registry.update_content(version_id, actor=me.name, ontology_ttl=body.turtle))


@router.get("/ontologies/industry")
def industry_ontologies():
    return INDUSTRY_ONTOLOGIES


@router.post("/versions/{version_id}/ontology/import")
def import_ontology(version_id: UUID, body: OntologyImportIn, request: Request, me: Principal = Depends(builder)):
    fmt, data = body.format, body.data
    if body.source:
        entry = INDUSTRY_ONTOLOGIES.get(body.source)
        if entry is None or not entry["url"]:
            raise ValueError(f"Unknown or non-fetchable industry ontology {body.source!r}")
        body.url, fmt = entry["url"], entry["format"]
    if body.url:
        import httpx
        r = httpx.get(body.url, follow_redirects=True, timeout=60.0)
        r.raise_for_status()
        if len(r.content) > 64 * 1024 * 1024:
            raise ValueError("Ontology file exceeds 64 MB")
        data = r.text
    if not data:
        raise ValueError("Provide data, url or source")
    if body.mode not in ("merge", "replace"):
        raise ValueError("mode must be merge or replace")
    try:
        incoming = Ontology.from_rdf(data, fmt)
    except Exception as exc:  # noqa: BLE001 - parser errors are user errors here
        raise ValueError(f"Could not parse ontology ({fmt}): {exc}") from None
    st = _st(request)
    current = st.registry.get_version(version_id).ontology_ttl
    if body.mode == "merge" and current:
        merged, report = merge_ontologies(Ontology.from_turtle(current), incoming)
    else:
        merged, report = incoming, {"classes_added": len(incoming.classes), "classes_skipped": 0,
                                    "properties_added": len(list(incoming.all_properties())), "properties_skipped": 0}
    st.registry.update_content(version_id, actor=me.name, ontology_ttl=merged.to_turtle())
    return {**_ontology_summary_json(merged), "report": report}


@router.put("/versions/{version_id}/ontology/json")
def put_ontology_json(version_id: UUID, body: dict, request: Request, me: Principal = Depends(builder)):
    """Save the ontology from its JSON form (what the editor holds); stored as Turtle like every other path."""
    try:
        onto = Ontology.from_dict(body)
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid ontology document: {exc}") from None
    _st(request).registry.update_content(version_id, actor=me.name, ontology_ttl=onto.to_turtle())
    return _ontology_summary_json(onto)


@router.get("/versions/{version_id}/ontology")
def get_ontology(version_id: UUID, request: Request):
    return _ontology(request, version_id).to_dict()


@router.get("/versions/{version_id}/ontology/turtle", response_class=PlainTextResponse)
def get_ontology_turtle(version_id: UUID, request: Request):
    return PlainTextResponse(_st(request).registry.get_version(version_id).ontology_ttl or "", media_type="text/turtle")


@router.get("/versions/{version_id}/ontology/checks")
def ontology_checks(version_id: UUID, request: Request):
    return _ontology(request, version_id).check()


@router.put("/versions/{version_id}/mapping")
def put_mapping(version_id: UUID, body: dict, request: Request, me: Principal = Depends(builder)):
    spec = MappingSpec.from_dict(body)
    spec.to_r2rml()  # validate before storing
    return _version_json(_st(request).registry.update_content(version_id, actor=me.name, mapping=spec.to_dict()))


@router.get("/versions/{version_id}/mapping")
def get_mapping(version_id: UUID, request: Request):
    return _st(request).registry.get_version(version_id).mapping or {}


@router.get("/versions/{version_id}/mapping/r2rml")
def get_r2rml(version_id: UUID, request: Request):
    return PlainTextResponse(serialize_r2rml(_spec(request, version_id).to_r2rml()), media_type="text/turtle")


def _class_triples_maps(spec: MappingSpec, class_iri: str) -> dict:
    """The triples maps that produce a class's entities: its own map plus relations it is the source of."""
    r2rml = spec.to_r2rml()
    subjects = {spec.subject_template(c) for c in spec.classes if c.class_iri == class_iri}
    return {iri: tm for iri, tm in r2rml.triples_maps.items() if class_iri in tm.classes or tm.subject.template in subjects}


@router.get("/versions/{version_id}/mapping/sql")
def get_sql(version_id: UUID, request: Request, dialect: str = Query(default="postgres"), class_iri: str | None = None):
    if dialect not in DIALECTS:
        raise ValueError(f"Unknown dialect {dialect!r}; choose from {sorted(DIALECTS)}")
    spec = _spec(request, version_id)
    if class_iri:
        from ontoforge.r2rml import Mapping
        maps = _class_triples_maps(spec, class_iri)
        if not maps:
            raise NotFound(f"Class {class_iri} has no mapping")
        mapping = Mapping(maps)
    else:
        mapping = spec.to_r2rml()
    return PlainTextResponse(compile_mapping(mapping, DIALECTS[dialect]()).sql, media_type="text/plain")


_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,2}$")


@router.get("/versions/{version_id}/mapping/table-preview")
def mapping_table_preview(version_id: UUID, request: Request, table: str, limit: int = Query(default=10, ge=1, le=200)):
    """First rows of a source table, for the assignment designer (columns are bound by clicking headers)."""
    if not _TABLE_NAME.match(table):
        raise ValueError(f"Invalid table name {table!r}")
    st = _st(request)
    columns, rows = st.source.query(f"SELECT * FROM {st.source.dialect.quote_table(table)}", limit)
    return {"columns": columns, "rows": [dict(zip(columns, (None if v is None else str(v) for v in r))) for r in rows]}


# -- mapping workflow ------------------------------------------------------------

@router.get("/versions/{version_id}/mapping/status")
def get_mapping_status(version_id: UUID, request: Request):
    version = _st(request).registry.get_version(version_id)
    spec = MappingSpec.from_dict(version.mapping) if version.mapping else MappingSpec(base_iri="")
    return mapping_status(_ontology(request, version_id), spec)


def _save_spec(request: Request, version_id: UUID, spec: MappingSpec, actor: str) -> dict:
    spec.to_r2rml()
    _st(request).registry.update_content(version_id, actor=actor, mapping=spec.to_dict())
    return spec.to_dict()


@router.post("/versions/{version_id}/mapping/exclude")
def mapping_exclude(version_id: UUID, body: ExcludeIn, request: Request, me: Principal = Depends(builder)):
    spec = _spec(request, version_id)
    classes = []
    for c in spec.classes:
        if c.class_iri == body.class_iri:
            excluded = set(c.excluded) | {body.property_iri} if body.excluded else set(c.excluded) - {body.property_iri}
            c = ClassMapping(c.class_iri, c.table, c.sql_query, c.key_columns, c.iri_template, c.attributes, tuple(excluded))
        classes.append(c)
    if body.class_iri not in {c.class_iri for c in classes}:
        raise NotFound(f"Class {body.class_iri} has no mapping")
    return _save_spec(request, version_id, MappingSpec(spec.base_iri, tuple(classes), spec.relations), me.name)


@router.post("/versions/{version_id}/mapping/exclude-unmapped")
def mapping_exclude_unmapped(version_id: UUID, request: Request, me: Principal = Depends(builder)):
    spec = _spec(request, version_id)
    status = {c.class_iri: c for c in mapping_status(_ontology(request, version_id), spec).classes}
    classes = tuple(ClassMapping(c.class_iri, c.table, c.sql_query, c.key_columns, c.iri_template, c.attributes,
                                 tuple(set(c.excluded) | set(status[c.class_iri].unmapped_attributes) | set(status[c.class_iri].unmapped_relations)))
                    if c.class_iri in status else c for c in spec.classes)
    return _save_spec(request, version_id, MappingSpec(spec.base_iri, classes, spec.relations), me.name)


@router.delete("/versions/{version_id}/mapping/classes")
def mapping_unmap_class(version_id: UUID, request: Request, class_iri: str, me: Principal = Depends(builder)):
    spec = _spec(request, version_id)
    classes = tuple(c for c in spec.classes if c.class_iri != class_iri)
    relations = tuple(r for r in spec.relations if class_iri not in (r.source_class, r.target_class))
    return _save_spec(request, version_id, MappingSpec(spec.base_iri, classes, relations), me.name)


@router.get("/versions/{version_id}/mapping/preview")
def mapping_preview(version_id: UUID, request: Request, class_iri: str, limit: int = Query(default=20, ge=1, le=500)):
    st = _st(request)
    spec = _spec(request, version_id)
    keep = _class_triples_maps(spec, class_iri)
    if not keep:
        raise NotFound(f"Class {class_iri} has no mapping")
    from ontoforge.r2rml import Mapping
    compiled = compile_mapping(Mapping(keep), st.source.dialect, column_types=st.source.catalog.resolver())
    columns, rows = st.source.query(compiled.sql, limit)
    return {"columns": columns, "rows": [dict(zip(columns, (None if v is None else str(v) for v in r))) for r in rows]}


@router.post("/versions/{version_id}/mapping/test-sql")
def mapping_test_sql(version_id: UUID, body: TestSqlIn, request: Request, me: Principal = Depends(builder)):
    columns, rows = _st(request).source.query(body.sql, body.limit)
    return {"columns": columns, "rows": [dict(zip(columns, (None if v is None else str(v) for v in r))) for r in rows]}


# -- versions: lifecycle ---------------------------------------------------------

@router.post("/versions/{version_id}/transition")
def transition(version_id: UUID, body: TransitionIn, request: Request, me: Principal = Depends(builder)):
    me.require({Status.IN_REVIEW: Role.BUILDER, Status.DRAFT: Role.REVIEWER, Status.PUBLISHED: Role.REVIEWER,
                Status.ARCHIVED: Role.ADMIN}[body.to])
    return _version_json(_st(request).registry.transition(version_id, body.to, actor=me.name))


@router.post("/versions/{version_id}/reviews", status_code=201)
def add_review(version_id: UUID, body: ReviewIn, request: Request, me: Principal = Depends(reviewer)):
    return _st(request).registry.add_review(version_id, reviewer=me.name, approved=body.approved, comment=body.comment)


@router.get("/versions/{version_id}/reviews")
def list_reviews(version_id: UUID, request: Request):
    return _st(request).registry.list_reviews(version_id)


@router.post("/versions/{version_id}/comments", status_code=201)
def add_comment(version_id: UUID, body: VersionCommentIn, request: Request, me: Principal = Depends(viewer)):
    return _st(request).registry.add_comment(version_id, author=me.name, body=body.body)


@router.get("/versions/{version_id}/comments")
def list_comments(version_id: UUID, request: Request):
    return _st(request).registry.list_comments(version_id)


@router.get("/versions/{version_id}/audit")
def audit(version_id: UUID, request: Request):
    return _st(request).registry.audit_trail(version_id)


@router.post("/versions/{version_id}/lease")
def acquire_lease(version_id: UUID, body: LeaseIn, request: Request, me: Principal = Depends(builder)):
    if body.force:
        me.require(Role.ADMIN)
    return _version_json(_st(request).registry.acquire_lease(version_id, editor=me.name, ttl=timedelta(seconds=body.ttl_seconds), force=body.force))


@router.delete("/versions/{version_id}/lease", status_code=204)
def release_lease(version_id: UUID, request: Request, me: Principal = Depends(builder)):
    _st(request).registry.release_lease(version_id, editor=me.name)
    return Response(status_code=204)


# -- builds ----------------------------------------------------------------------

@router.post("/versions/{version_id}/builds", status_code=202)
def build(version_id: UUID, request: Request, response: Response, me: Principal = Depends(builder),
          wait: bool = Query(default=False, description="block until the build finishes")):
    """Starts a build in the background (202 + running run). ``?wait=true`` returns the finished run (200)."""
    sched = _st(request).scheduler
    run = sched.submit(version_id, actor=me.name)
    if wait:
        response.status_code = 200
        return sched.wait(run.id)
    return run


@router.post("/builds/{run_id}/cancel")
def cancel_build(run_id: UUID, request: Request, me: Principal = Depends(builder)):
    if not _st(request).scheduler.cancel(run_id):
        raise LifecycleError("Build is not running")
    return {"id": run_id, "cancelling": True}


@router.get("/versions/{version_id}/builds")
def list_builds(version_id: UUID, request: Request):
    return _st(request).registry.list_builds(version_id)


@router.get("/builds/{run_id}")
def get_build(run_id: UUID, request: Request):
    return _st(request).registry.get_build(run_id)


# -- graph -----------------------------------------------------------------------

@router.get("/versions/{version_id}/graph/status")
def graph_status(version_id: UUID, request: Request):
    st = _st(request)
    st.registry.get_version(version_id)
    return {"triples": st.store.count(version_id), "inferred": st.store.count(version_id, inferred=True),
            "types": dict(st.store.type_inventory(version_id)), "predicates": dict(st.store.predicate_inventory(version_id)),
            "last_build": st.registry.latest_build(version_id)}


@router.get("/versions/{version_id}/graph/search")
def graph_search(version_id: UUID, request: Request, q: str = Query(default=""), type: str | None = None,
                 limit: int = Query(default=20, ge=1, le=200),
                 match: str = Query(default="contains", pattern="^(contains|exact|starts_with|ends_with)$"),
                 field: str = Query(default="any", pattern="^(any|label|iri)$")):
    return _st(request).store.search(version_id, q, type_iri=type, limit=limit, match=match, field=field)


@router.get("/versions/{version_id}/graph/overview")
def graph_overview(version_id: UUID, request: Request, limit: int = Query(default=300, ge=10, le=2000)):
    return _st(request).store.overview(version_id, limit)


@router.get("/versions/{version_id}/graph/triples")
def graph_triples(version_id: UUID, request: Request, subject: str | None = None, predicate: str | None = None,
                  text: str | None = None, inferred: bool | None = None, sort: str = "subject", direction: str = "asc",
                  limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0)):
    return _st(request).store.triples(version_id, subject=subject, predicate=predicate, text=text, inferred=inferred,
                                      limit=limit, offset=offset, sort=sort, direction=direction)


@router.get("/versions/{version_id}/graph/entity")
def graph_entity(version_id: UUID, request: Request, iri: str):
    st = _st(request)
    detail = st.store.describe(version_id, iri)
    if detail is None:
        raise NotFound(f"Entity {iri}")
    summary = {"datasets": [], "actions": [], "virtual_attributes": [], "bridges": []}
    for t in detail.types:
        info = st.attachments.for_class(version_id, t)
        summary["datasets"] += [d["table"] for d in info["datasets"]]
        summary["actions"] += [a["name"] for a in info["actions"]]
        summary["virtual_attributes"] += info["virtual_attributes"]
        summary["bridges"] += [b["target_domain"] for b in info["bridges"]]
    return {**asdict(detail), "attachments": {k: sorted(v) for k, v in summary.items()}}


@router.get("/versions/{version_id}/graph/entity/virtual")
def entity_virtual(version_id: UUID, request: Request, iri: str):
    return _st(request).attachments.compute_virtual(version_id, iri)


@router.post("/versions/{version_id}/graph/entity/actions/{name}")
def entity_action(version_id: UUID, name: str, request: Request, iri: str, me: Principal = Depends(viewer)):
    try:
        return _st(request).attachments.invoke(version_id, iri, name)
    except AttachmentError as exc:
        if "no action" in str(exc):
            raise NotFound(str(exc))
        raise


@router.get("/versions/{version_id}/graph/entity/bridges")
def entity_bridges(version_id: UUID, request: Request, iri: str):
    return _st(request).attachments.bridges_for(version_id, iri)


@router.get("/versions/{version_id}/graph/entity/datasets")
def entity_datasets(version_id: UUID, request: Request, iri: str, limit: int = Query(default=50, ge=1, le=500)):
    return _st(request).attachments.dataset_rows(version_id, iri, limit)


@router.put("/versions/{version_id}/attachments")
def put_attachments(version_id: UUID, body: dict, request: Request, me: Principal = Depends(builder)):
    att = Attachments.from_dict(body)
    onto = _ontology(request, version_id)
    unknown = [c for c in att.classes() if c not in onto.classes]
    if unknown:
        raise AttachmentError(f"Unknown class(es): {', '.join(sorted(unknown))}")
    for b in att.bridges:
        try:
            _st(request).registry.get_domain(b.target_domain)
        except NotFound:
            raise AttachmentError(f"Bridge target domain {b.target_domain!r} does not exist")
    _st(request).registry.update_content(version_id, actor=me.name, attachments=att.to_dict())
    return att.to_dict()


@router.get("/versions/{version_id}/attachments")
def get_attachments(version_id: UUID, request: Request):
    return _st(request).registry.get_version(version_id).attachments or Attachments().to_dict()


@router.get("/versions/{version_id}/graph/neighbourhood")
def graph_neighbourhood(version_id: UUID, request: Request, iri: str, depth: int = Query(default=1, ge=0, le=6),
                        limit: int = Query(default=200, ge=1, le=2000)):
    return _st(request).store.neighbourhood(version_id, iri, depth=depth, limit=limit)


# -- reasoning -------------------------------------------------------------------

@router.post("/versions/{version_id}/reasoning/infer")
def infer(version_id: UUID, request: Request, me: Principal = Depends(builder)):
    return _st(request).reasoner.owl_rl(version_id)


@router.post("/versions/{version_id}/reasoning/validate")
def validate(version_id: UUID, request: Request, me: Principal = Depends(builder)):
    return _st(request).reasoner.validate(version_id)


@router.get("/versions/{version_id}/reasoning/shapes")
def shapes(version_id: UUID, request: Request):
    return PlainTextResponse(generate_shapes(_ontology(request, version_id)), media_type="text/turtle")


# -- graphql ---------------------------------------------------------------------

@router.post("/versions/{version_id}/graphql")
def graphql(version_id: UUID, body: GraphQLIn, request: Request):
    st = _st(request)
    result = graphql_sync(build_schema(st.registry, st.store, version_id), body.query, variable_values=body.variables)
    out = {"data": result.data}
    if result.errors:
        out["errors"] = [{"message": e.message, "path": e.path} for e in result.errors]
    return out


@router.get("/versions/{version_id}/graphql/schema")
def graphql_schema(version_id: UUID, request: Request):
    st = _st(request)
    return PlainTextResponse(print_schema(build_schema(st.registry, st.store, version_id)), media_type="text/plain")


# -- catalog / autodraft ---------------------------------------------------------

@router.get("/catalog/tables")
def catalog_tables(request: Request, schema_name: str | None = None):
    return _st(request).source.catalog.list_tables(schema_name)


@router.get("/catalog/tables/{table}")
def catalog_table(table: str, request: Request):
    cat = _st(request).source.catalog
    return {"table": table, "columns": [{"name": n, "type": t} for n, t in cat.column_types(table).items()],
            "primary_key": list(cat.primary_key(table)),
            "foreign_keys": [{"columns": list(c), "references": r, "referenced_columns": list(rc)} for c, r, rc in cat.foreign_keys(table)]}


@router.post("/versions/{version_id}/autodraft")
def autodraft(version_id: UUID, body: AutodraftIn, request: Request, me: Principal = Depends(builder)):
    st = _st(request)
    version = st.registry.get_version(version_id)
    domain = st.registry.get_domain_by_id(version.domain_id)
    onto, spec = draft_from_catalog(st.source.catalog, ontology_iri=body.ontology_iri, base_iri=domain.base_iri,
                                    tables=body.tables, schema=body.schema_name, infer=body.infer_keys)
    st.registry.update_content(version_id, actor=me.name, ontology_ttl=onto.to_turtle(), mapping=spec.to_dict())
    return {"classes": len(onto.classes), "properties": len(onto.datatype_properties) + len(onto.object_properties),
            "relations": len(spec.relations), "issues": onto.check()}


# -- rules -----------------------------------------------------------------------

@router.put("/versions/{version_id}/rules")
def put_rules(version_id: UUID, body: RulesIn, request: Request, me: Principal = Depends(builder)):
    onto = _ontology(request, version_id)
    rs = RuleSet(Rule.from_text(r.text, onto, r.name, r.mode, r.enabled) for r in body.rules)
    _st(request).registry.update_content(version_id, actor=me.name, rules=rs.to_dict())
    return rs.to_dict()


@router.get("/versions/{version_id}/rules")
def get_rules(version_id: UUID, request: Request):
    return _st(request).registry.get_version(version_id).rules or {"rules": []}


@router.get("/versions/{version_id}/rules/sql")
def rules_sql(version_id: UUID, request: Request):
    rs = RuleSet.from_dict(_st(request).registry.get_version(version_id).rules)
    parts = []
    for r in rs.rules:
        parts.append(f"-- {r.name} ({r.mode}{'' if r.enabled else ', disabled'})\n" +
                     ("\n".join(RuleEngine.compile_insert(r, version_id)) if r.mode == "materialize" else RuleEngine.compile_select(r, version_id)))
    return PlainTextResponse("\n\n".join(parts), media_type="text/plain")


@router.post("/versions/{version_id}/reasoning/rules")
def run_rules(version_id: UUID, request: Request, me: Principal = Depends(builder)):
    st = _st(request)
    return RuleEngine(st.registry, st.store).run(version_id)


# -- data quality ----------------------------------------------------------------

def _validated_constraints(request: Request, version_id: UUID, cs: ConstraintSet) -> ConstraintSet:
    onto = _ontology(request, version_id)
    props = {p.iri for p in onto.all_properties()}
    for c in cs.constraints:
        if c.target_class not in onto.classes:
            raise QualityError(f"Constraint {c.name!r}: unknown class {c.target_class}")
        if c.property is not None and c.property not in props:
            raise QualityError(f"Constraint {c.name!r}: unknown property {c.property}")
    return cs


@router.put("/versions/{version_id}/quality")
def put_quality(version_id: UUID, body: dict, request: Request, me: Principal = Depends(builder)):
    cs = _validated_constraints(request, version_id, ConstraintSet.from_dict(body))
    _st(request).registry.update_content(version_id, actor=me.name, quality=cs.to_dict())
    return cs.to_dict()


@router.get("/versions/{version_id}/quality")
def get_quality(version_id: UUID, request: Request):
    return _st(request).registry.get_version(version_id).quality or {"constraints": []}


@router.get("/versions/{version_id}/quality/shacl")
def quality_shacl(version_id: UUID, request: Request):
    cs = ConstraintSet.from_dict(_st(request).registry.get_version(version_id).quality)
    return PlainTextResponse(cs.to_shacl(), media_type="text/turtle")


@router.post("/versions/{version_id}/quality/import-shacl")
def quality_import_shacl(version_id: UUID, body: OntologyIn, request: Request, me: Principal = Depends(builder)):
    cs = _validated_constraints(request, version_id, ConstraintSet.from_shacl(body.turtle))
    _st(request).registry.update_content(version_id, actor=me.name, quality=cs.to_dict())
    return cs.to_dict()


@router.get("/versions/{version_id}/quality/sql")
def quality_sql(version_id: UUID, request: Request):
    st = _st(request)
    return PlainTextResponse(QualityEngine(st.registry, st.store).sql(version_id), media_type="text/plain")


@router.post("/versions/{version_id}/reasoning/quality")
def run_quality(version_id: UUID, request: Request, me: Principal = Depends(builder),
                include_ontology: bool = Query(default=True)):
    st = _st(request)
    report = QualityEngine(st.registry, st.store).run(version_id, include_ontology)
    return {"conforms": report.conforms, "summary": report.summary, "results": report.results}


# -- cohorts ---------------------------------------------------------------------

def _validated_cohort(request: Request, version_id: UUID, body: dict, name: str | None = None) -> Cohort:
    cohort = Cohort.from_dict({**body, "name": name or body.get("name")})
    onto = _ontology(request, version_id)
    if cohort.class_iri not in onto.classes:
        raise CohortError(f"Unknown class {cohort.class_iri}")
    props = {p.iri for p in onto.all_properties()}
    for c in cohort.criteria:
        for prop in (c.property, c.via):
            if prop and prop not in props:
                raise CohortError(f"Unknown property {prop}")
    return cohort


@router.post("/versions/{version_id}/cohorts/evaluate")
def cohort_evaluate(version_id: UUID, body: dict, request: Request, limit: int = Query(default=200, ge=1, le=5000)):
    return _st(request).cohorts.evaluate(version_id, _validated_cohort(request, version_id, body), limit)


@router.get("/versions/{version_id}/cohorts")
def cohort_list(version_id: UUID, request: Request):
    return [c.to_dict() for c in _st(request).cohorts.list(version_id)]


@router.put("/versions/{version_id}/cohorts/{name}")
def cohort_put(version_id: UUID, name: str, body: dict, request: Request, me: Principal = Depends(builder)):
    return _st(request).cohorts.save(version_id, _validated_cohort(request, version_id, body, name), actor=me.name).to_dict()


@router.get("/versions/{version_id}/cohorts/{name}/members")
def cohort_members(version_id: UUID, name: str, request: Request, limit: int = Query(default=200, ge=1, le=5000)):
    eng = _st(request).cohorts
    return eng.evaluate(version_id, eng.get(version_id, name), limit)


@router.post("/versions/{version_id}/cohorts/{name}/materialise")
def cohort_materialise(version_id: UUID, name: str, request: Request, me: Principal = Depends(builder)):
    return _st(request).cohorts.materialise(version_id, name)


@router.delete("/versions/{version_id}/cohorts/{name}", status_code=204)
def cohort_delete(version_id: UUID, name: str, request: Request, me: Principal = Depends(builder)):
    _st(request).cohorts.delete(version_id, name, actor=me.name)
    return Response(status_code=204)


# -- analytics -------------------------------------------------------------------

@router.post("/versions/{version_id}/analytics/communities")
def analytics_communities(version_id: UUID, body: CommunitiesIn, request: Request, me: Principal = Depends(builder)):
    r = _st(request).analytics.communities(version_id, body.algorithm, body.resolution, body.seed, body.persist, actor=me.name)
    return {"run_id": r.run_id, "algorithm": r.algorithm, "resolution": r.resolution, "count": r.count,
            "communities": r.communities, "persisted": r.persisted}


@router.post("/versions/{version_id}/analytics/centralities")
def analytics_centralities(version_id: UUID, body: CentralitiesIn, request: Request, me: Principal = Depends(builder)):
    r = _st(request).analytics.centralities(version_id, body.top_n, actor=me.name)
    return {"run_id": r.run_id, "kpis": r.kpis, "histograms": r.histograms, "top": r.top, "estimated": r.estimated}


@router.get("/versions/{version_id}/analytics/health")
def analytics_health(version_id: UUID, request: Request):
    return _st(request).analytics.health(version_id)


@router.get("/versions/{version_id}/analytics/runs")
def analytics_runs(version_id: UUID, request: Request):
    return _st(request).registry.list_analytics(version_id)


@router.get("/analytics/runs/{run_id}")
def analytics_run(run_id: UUID, request: Request):
    return _st(request).registry.get_analytics(run_id)


@router.post("/analytics/runs/{run_id}/interpret")
def analytics_interpret(run_id: UUID, request: Request, me: Principal = Depends(builder),
                        comment: bool = Query(default=False, description="also post the insight as a version comment")):
    from ontoforge.analytics import insight_markdown, interpret_run
    st = _st(request)
    insight = interpret_run(st.registry, st.store, run_id, _llm(request))
    if comment:
        st.registry.add_comment(st.registry.get_analytics(run_id).domain_version_id, author=me.name, body=insight_markdown(insight))
    return insight


# -- metadata --------------------------------------------------------------------

@router.post("/versions/{version_id}/metadata/import")
def metadata_import(version_id: UUID, body: MetadataImportIn, request: Request, me: Principal = Depends(builder)):
    _st(request).metadata.import_tables(version_id, body.tables, actor=me.name, schema=body.schema_name)
    return _st(request).metadata.list(version_id)


@router.get("/versions/{version_id}/metadata")
def metadata_list(version_id: UUID, request: Request):
    return _st(request).metadata.list(version_id)


@router.post("/versions/{version_id}/metadata/refresh")
def metadata_refresh(version_id: UUID, request: Request, me: Principal = Depends(builder)):
    return _st(request).metadata.refresh(version_id, actor=me.name)


@router.put("/versions/{version_id}/metadata/{table}/columns/{column}")
def metadata_column_comment(version_id: UUID, table: str, column: str, body: CommentIn, request: Request,
                            me: Principal = Depends(builder)):
    return _st(request).metadata.set_comment(version_id, table, column, body.comment, actor=me.name)


@router.put("/versions/{version_id}/metadata/{table}")
def metadata_table_comment(version_id: UUID, table: str, body: CommentIn, request: Request, me: Principal = Depends(builder)):
    return _st(request).metadata.set_comment(version_id, table, None, body.comment, actor=me.name)


@router.delete("/versions/{version_id}/metadata/{table}", status_code=204)
def metadata_remove(version_id: UUID, table: str, request: Request, me: Principal = Depends(builder)):
    _st(request).metadata.remove(version_id, table, actor=me.name)
    return Response(status_code=204)


@router.get("/versions/{version_id}/mapping/drift")
def mapping_drift(version_id: UUID, request: Request):
    return _st(request).metadata.drift(version_id)


# -- llm -------------------------------------------------------------------------

def _llm(request: Request):
    llm = _st(request).llm
    if llm is None:
        raise LLMUnavailable("No LLM provider configured (set ONTOFORGE_LLM_PROVIDER=anthropic)")
    return llm


def _tables(request: Request, tables: list[str] | None, schema: str | None, version_id: UUID | None = None) -> list[dict]:
    st = _st(request)
    snapshots = {s.table: s for s in st.metadata.list(version_id)} if version_id else {}
    return describe_tables(st.source.catalog, tables, schema, sample_rows=lambda t: _samples(request, t), snapshots=snapshots)


def _samples(request: Request, table: str, n: int = 3) -> list[tuple]:
    src = _st(request).source
    try:
        return list(src.stream(f"SELECT * FROM {src.dialect.quote_table(table)} LIMIT {n}", batch=n))[:n]
    except Exception:  # noqa: BLE001 - samples are a nicety, never a failure
        return []


@router.post("/versions/{version_id}/llm/draft-ontology")
def llm_draft_ontology(version_id: UUID, body: DraftOntologyIn, request: Request, me: Principal = Depends(builder)):
    onto = OntologyDrafter(_llm(request)).draft(body.ontology_iri, _tables(request, body.tables, body.schema_name, version_id), body.description)
    _st(request).registry.update_content(version_id, actor=me.name, ontology_ttl=onto.to_turtle())
    return _ontology_summary_json(onto)


@router.post("/versions/{version_id}/llm/suggest-mapping")
def llm_suggest_mapping(version_id: UUID, body: SuggestMappingIn, request: Request, me: Principal = Depends(builder)):
    st = _st(request)
    version = st.registry.get_version(version_id)
    domain = st.registry.get_domain_by_id(version.domain_id)
    spec = MappingSuggester(_llm(request)).suggest(_ontology(request, version_id), _tables(request, body.tables, body.schema_name, version_id), domain.base_iri)
    st.registry.update_content(version_id, actor=me.name, mapping=spec.to_dict())
    return {"classes": len(spec.classes), "relations": len(spec.relations), "mapping": spec.to_dict()}


@router.post("/versions/{version_id}/llm/assist")
def llm_assist(version_id: UUID, body: AssistIn, request: Request, me: Principal = Depends(builder)):
    onto = OntologyAssistant(_llm(request)).edit(_ontology(request, version_id), body.instruction)
    _st(request).registry.update_content(version_id, actor=me.name, ontology_ttl=onto.to_turtle())
    return _ontology_summary_json(onto)


def _ontology_summary_json(onto: Ontology) -> dict:
    return {"classes": len(onto.classes), "properties": len(onto.datatype_properties) + len(onto.object_properties),
            "issues": onto.check(), "ontology": onto.to_dict()}


# -- helpers ---------------------------------------------------------------------

def _ontology(request: Request, version_id: UUID) -> Ontology:
    ttl = _st(request).registry.get_version(version_id).ontology_ttl
    if not ttl:
        raise NotFound("Version has no ontology")
    return Ontology.from_turtle(ttl)


def _spec(request: Request, version_id: UUID) -> MappingSpec:
    mapping = _st(request).registry.get_version(version_id).mapping
    if not mapping:
        raise NotFound("Version has no mapping")
    return MappingSpec.from_dict(mapping)


# -- domain settings and connections (Configure screen) ---------------------------

@router.put("/domains/{name}")
def update_domain(name: str, body: DomainUpdateIn, request: Request, me: Principal = Depends(builder)):
    st = _st(request)
    changes = body.model_dump(exclude_unset=True)
    for key in ("connection_id", "ai_connection_id"):
        if changes.get(key):
            st.connections.get(str(changes[key]))   # NotFound when the backend does not know it
    return st.registry.update_domain(st.registry.get_domain(name).id, changes, actor=me.name)


@router.get("/domains/{name}/source")
def domain_source(name: str, request: Request):
    st = _st(request)
    return _source_facts(st, st.registry.get_domain(name))


@router.get("/connectors")
def list_connectors(request: Request):
    """The adapters this deployment can configure, with the fields the Configure form renders."""
    return _st(request).connections.specs()


@router.get("/connections")
def list_connections(request: Request):
    return _st(request).connections.list()


@router.post("/connections", status_code=201)
def create_connection(body: ConnectionIn, request: Request, me: Principal = Depends(admin)):
    return _st(request).connections.create(body.name, body.kind, body.config, body.secret, actor=me.name)


@router.get("/connections/{connection_id}")
def get_connection(connection_id: str, request: Request):
    return _st(request).connections.get(connection_id)


@router.put("/connections/{connection_id}")
def update_connection(connection_id: str, body: ConnectionUpdateIn, request: Request, me: Principal = Depends(admin)):
    return _st(request).connections.update(connection_id, name=body.name, config=body.config, secret=body.secret, actor=me.name)


@router.delete("/connections/{connection_id}", status_code=204)
def delete_connection(connection_id: str, request: Request, me: Principal = Depends(admin)):
    st = _st(request)
    st.connections.delete(connection_id, actor=me.name)
    try:
        st.registry.detach_connection(UUID(connection_id))
    except ValueError:
        pass   # a non-uuid hub id cannot be referenced by a domain column
    return Response(status_code=204)


@router.post("/connections/test")
def test_connection_draft(body: ConnectionTestIn, request: Request, me: Principal = Depends(builder)):
    """Probe an unsaved configuration (the Configure form's Test button before saving)."""
    return _st(request).connections.test_draft(body.kind, body.config, body.secret)


@router.post("/connections/{connection_id}/test")
def test_connection(connection_id: str, request: Request, me: Principal = Depends(builder)):
    return _st(request).connections.test(connection_id, actor=me.name)
