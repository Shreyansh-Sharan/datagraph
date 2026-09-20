from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import PlainTextResponse
from graphql import graphql_sync, print_schema
from pydantic import BaseModel, Field

from ontoforge.auth import Principal, Role
from ontoforge.auth.fastapi import admin, builder, reviewer, viewer
from ontoforge.autodraft import draft_from_catalog
from ontoforge.bundle import export_bundle, import_bundle
from ontoforge.compiler import compile_mapping
from ontoforge.dialects import DIALECTS
from ontoforge.graphql import build_schema
from ontoforge.llm import LLMUnavailable, MappingSuggester, OntologyAssistant, OntologyDrafter, describe_tables
from ontoforge.mapping import MappingSpec
from ontoforge.ontology import Ontology
from ontoforge.r2rml import serialize_r2rml
from ontoforge.reasoning import generate_shapes
from ontoforge.quality import ConstraintSet, QualityEngine, QualityError
from ontoforge.rules import Rule, RuleEngine, RuleError, RuleSet
from ontoforge.registry import DomainVersion, LifecycleError, NotFound, Status

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


class OntologyIn(BaseModel):
    turtle: str


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


class MetadataImportIn(BaseModel):
    tables: list[str]
    schema_name: str | None = None


class CommentIn(BaseModel):
    comment: str | None


class AutodraftIn(BaseModel):
    ontology_iri: str
    tables: list[str] | None = None
    schema_name: str | None = None


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


@router.get("/domains/{name}")
def get_domain(name: str, request: Request):
    return _st(request).registry.get_domain(name)


@router.delete("/domains/{name}", status_code=204)
def delete_domain(name: str, request: Request, me: Principal = Depends(admin)):
    reg = _st(request).registry
    reg.delete_domain(reg.get_domain(name).id)
    return Response(status_code=204)


@router.get("/domains/{name}/export")
def export_domain(name: str, request: Request, version_id: UUID | None = None):
    return export_bundle(_st(request).registry, name, version_id)


@router.post("/domains/import", status_code=201)
def import_domain(body: dict, request: Request, me: Principal = Depends(builder)):
    return _version_json(import_bundle(_st(request).registry, body, actor=me.name, name=body.get("name")))


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


@router.get("/versions/{version_id}/mapping/sql")
def get_sql(version_id: UUID, request: Request, dialect: str = Query(default="postgres")):
    if dialect not in DIALECTS:
        raise ValueError(f"Unknown dialect {dialect!r}; choose from {sorted(DIALECTS)}")
    compiled = compile_mapping(_spec(request, version_id).to_r2rml(), DIALECTS[dialect]())
    return PlainTextResponse(compiled.sql, media_type="text/plain")


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
                 limit: int = Query(default=20, ge=1, le=200)):
    return _st(request).store.search(version_id, q, type_iri=type, limit=limit)


@router.get("/versions/{version_id}/graph/entity")
def graph_entity(version_id: UUID, request: Request, iri: str):
    detail = _st(request).store.describe(version_id, iri)
    if detail is None:
        raise NotFound(f"Entity {iri}")
    return detail


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
                                    tables=body.tables, schema=body.schema_name)
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
        if c.property not in props:
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
