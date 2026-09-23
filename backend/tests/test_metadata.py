"""Metadata snapshots per version, refresh diffs, comments, dependency checks, and schema drift."""
import pytest
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.build import BuildPipeline, PostgresSource
from ontoforge.catalog import PostgresCatalog
from ontoforge.config import Settings
from ontoforge.llm import describe_tables
from ontoforge.metadata import MetadataService, MetadataError
from ontoforge.registry import Registry
from ontoforge.store import TripleStore
from tests.hr_fixture import seed_tables, mapping, ontology, BASE, EX

ADMIN = Settings(auth_default_role="admin")


def prepared(db):
    seed_tables(db)
    with db.transaction() as cur:
        cur.execute("COMMENT ON COLUMN employees.sal IS 'Monthly salary in EUR'")
        cur.execute("COMMENT ON TABLE departments IS 'Org units'")
    reg = Registry(db)
    v = reg.create_version(reg.create_domain("hr", base_iri=BASE).id, actor="a")
    reg.update_content(v.id, actor="a", ontology_ttl=ontology().to_turtle(), mapping=mapping().to_dict())
    return reg, MetadataService(reg, PostgresCatalog(db), db), v


def test_import_snapshots_columns_keys_and_comments(db):
    reg, meta, v = prepared(db)
    snaps = meta.import_tables(v.id, ["employees", "departments"], actor="a")
    emp = next(s for s in snaps if s.table == "employees")
    assert [c["name"] for c in emp.columns][:3] == ["empno", "ename", "sal"]
    assert next(c for c in emp.columns if c["name"] == "sal")["comment"] == "Monthly salary in EUR"
    assert emp.primary_key == ["empno"] and any(f["references"] == "departments" for f in emp.foreign_keys)
    assert next(s for s in snaps if s.table == "departments").comment == "Org units"
    assert [s.table for s in meta.list(v.id)] == ["departments", "employees"]


def test_import_requires_an_editable_draft(db):
    reg, meta, v = prepared(db)
    reg.acquire_lease(v.id, editor="someone-else", ttl=__import__("datetime").timedelta(minutes=5))
    with pytest.raises(Exception, match="someone-else"):
        meta.import_tables(v.id, ["employees"], actor="a")


def test_refresh_reports_added_removed_modified_and_keeps_comments(db):
    reg, meta, v = prepared(db)
    meta.import_tables(v.id, ["employees"], actor="a")
    meta.set_comment(v.id, "employees", "ename", "Display name", actor="a")
    with db.transaction() as cur:
        cur.execute("ALTER TABLE employees ADD COLUMN email text")
        cur.execute("ALTER TABLE employees DROP COLUMN hired")
        cur.execute("ALTER TABLE employees ALTER COLUMN sal TYPE double precision")
    diff = meta.refresh(v.id, actor="a")
    (change,) = diff
    assert change.table == "employees" and change.added == ["email"] and change.removed == ["hired"]
    assert change.modified == [{"column": "sal", "from": "numeric", "to": "double precision"}]
    emp = meta.get(v.id, "employees")
    assert next(c for c in emp.columns if c["name"] == "ename")["comment"] == "Display name"   # user comment survives
    assert next(c for c in emp.columns if c["name"] == "sal")["comment"] == "Monthly salary in EUR"


def test_refresh_flags_tables_that_disappeared(db):
    reg, meta, v = prepared(db)
    meta.import_tables(v.id, ["collaborations"], actor="a")
    with db.transaction() as cur:
        cur.execute("DROP TABLE collaborations")
    (change,) = meta.refresh(v.id, actor="a")
    assert change.missing is True


def test_remove_is_blocked_while_mapping_uses_the_table(db):
    reg, meta, v = prepared(db)
    meta.import_tables(v.id, ["employees", "employee_skills"], actor="a")
    with pytest.raises(MetadataError, match="Employee"):
        meta.remove(v.id, "employees", actor="a")
    meta.remove(v.id, "employee_skills", actor="a")
    assert [s.table for s in meta.list(v.id)] == ["employees"]


def test_drift_compares_mapping_to_snapshot_and_live_catalog(db):
    reg, meta, v = prepared(db)
    meta.import_tables(v.id, ["employees", "departments", "collaborations"], actor="a")
    assert meta.drift(v.id) == []
    with db.transaction() as cur:
        cur.execute("ALTER TABLE employees DROP COLUMN sal")
        cur.execute("ALTER TABLE employees RENAME COLUMN deptno TO dept_id")
        cur.execute("ALTER TABLE departments ALTER COLUMN dname TYPE varchar(50)")
    issues = {(i.kind, i.table, i.column) for i in meta.drift(v.id)}
    assert ("missing-column", "employees", "sal") in issues            # attribute salary
    assert ("missing-column", "employees", "deptno") in issues         # relation worksIn target_key
    assert ("type-changed", "departments", "dname") in issues
    assert all(i.mapping_ref for i in meta.drift(v.id) if i.kind == "missing-column")


def test_drift_without_snapshot_still_checks_live_catalog(db):
    reg, meta, v = prepared(db)
    with db.transaction() as cur:
        cur.execute("ALTER TABLE departments DROP COLUMN dname")
    assert ("missing-column", "departments", "dname") in {(i.kind, i.table, i.column) for i in meta.drift(v.id)}


def test_build_records_drift_as_a_non_blocking_step(db):
    reg, meta, v = prepared(db)
    meta.import_tables(v.id, ["departments"], actor="a")
    with db.transaction() as cur:
        cur.execute("ALTER TABLE departments ALTER COLUMN dname TYPE varchar(50)")
    run = BuildPipeline(reg, TripleStore(db), PostgresSource(db), metadata=meta).run(v.id)
    assert run.status == "succeeded", run.error
    drift = next(s for s in run.steps if s["name"] == "drift")
    assert drift["detail"]["issues"][0]["kind"] == "type-changed"


def test_describe_tables_prefers_snapshot_comments(db):
    reg, meta, v = prepared(db)
    snaps = meta.import_tables(v.id, ["employees"], actor="a")
    (t,) = describe_tables(PostgresCatalog(db), ["employees"], snapshots={s.table: s for s in snaps})
    assert next(c for c in t["columns"] if c["name"] == "sal")["comment"] == "Monthly salary in EUR"


def test_metadata_endpoints(db):
    seed_tables(db)
    with TestClient(create_app(db=db, settings=ADMIN), headers={"X-Actor": "alice"}) as c:
        c.post("/domains", json={"name": "hr", "base_iri": BASE})
        v = c.post("/domains/hr/versions").json()
        c.put(f"/versions/{v['id']}/mapping", json=mapping().to_dict())
        r = c.post(f"/versions/{v['id']}/metadata/import", json={"tables": ["employees", "departments"]})
        assert r.status_code == 200 and [t["table"] for t in r.json()] == ["departments", "employees"]
        assert c.put(f"/versions/{v['id']}/metadata/employees/columns/ename", json={"comment": "Name"}).status_code == 200
        assert next(col for col in c.get(f"/versions/{v['id']}/metadata").json()[1]["columns"] if col["name"] == "ename")["comment"] == "Name"
        with db.transaction() as cur:
            cur.execute("ALTER TABLE employees ADD COLUMN email text")
        assert c.post(f"/versions/{v['id']}/metadata/refresh").json()[0]["added"] == ["email"]
        assert c.get(f"/versions/{v['id']}/mapping/drift").json() == {"checked": False, "issues": [], "at": None}
        assert c.delete(f"/versions/{v['id']}/metadata/employees").status_code == 409
        assert c.delete(f"/versions/{v['id']}/metadata/departments").status_code == 409  # Department is mapped too
        assert c.get(f"/versions/{v['id']}/metadata", headers={"X-Actor": "viewer-only"}).status_code == 200


def test_drift_says_when_it_was_never_checked(db):
    """"No drift" and "nobody looked" are different answers, and a screen must be able to tell."""
    from ontoforge.metadata import drift_from_last_build
    from ontoforge.registry import Registry

    reg = Registry(db)
    d = reg.create_domain("dr", base_iri="http://d/dr/")
    v = reg.create_version(d.id, actor="a")
    assert drift_from_last_build(reg, v.id) == {"checked": False, "issues": [], "at": None}

    run = reg.start_build(v.id, actor="a")
    reg.finish_build(run.id, status="succeeded", triple_count=0,
                     steps=[{"name": "drift", "detail": {"issues": [{"kind": "missing-column", "table": "t"}], "tables": 1}}])
    out = drift_from_last_build(reg, v.id)
    assert out["checked"] is True and len(out["issues"]) == 1 and out["at"]
