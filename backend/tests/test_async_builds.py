"""Builds run in the background: submit, poll progress, cancel, recover stale runs."""
import threading
import time

import pytest
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.build import BuildPipeline, BuildScheduler, PostgresSource
from ontoforge.config import Settings
from ontoforge.registry import Registry
from ontoforge.store import TripleStore
from tests.hr_fixture import seed_tables, mapping, ontology, BASE

ADMIN = Settings(auth_default_role="admin")


def prepared(db):
    seed_tables(db)
    reg = Registry(db)
    v = reg.create_version(reg.create_domain("hr", base_iri=BASE).id, actor="a")
    reg.update_content(v.id, actor="a", ontology_ttl=ontology().to_turtle(), mapping=mapping().to_dict())
    return reg, TripleStore(db), v


def wait_for(fn, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        out = fn()
        if out:
            return out
        time.sleep(0.05)
    raise AssertionError("timed out")


def test_scheduler_runs_build_in_background_and_records_progress(db):
    reg, store, v = prepared(db)
    sched = BuildScheduler(BuildPipeline(reg, store, PostgresSource(db)), reg)
    run = sched.submit(v.id, actor="a")
    assert run.status == "running"
    done = wait_for(lambda: (r := reg.get_build(run.id)) and r.status != "running" and r)
    assert done.status == "succeeded" and done.triple_count == store.count(v.id) > 0
    assert [s["name"] for s in done.steps] == ["compile", "prepare", "plan", "load", "finalize"]
    assert all(s.get("seconds") is not None for s in done.steps)
    sched.shutdown()


def test_only_one_running_build_per_version(db):
    reg, store, v = prepared(db)
    gate = threading.Event()

    class SlowPipeline(BuildPipeline):
        def run(self, version_id, *, actor=None, run=None, cancel_check=None, **kw):
            gate.wait(5)
            return super().run(version_id, actor=actor, run=run, cancel_check=cancel_check, **kw)

    sched = BuildScheduler(SlowPipeline(reg, store, PostgresSource(db)), reg)
    first = sched.submit(v.id, actor="a")
    with pytest.raises(Exception, match="already running"):
        sched.submit(v.id, actor="a")
    gate.set()
    wait_for(lambda: reg.get_build(first.id).status != "running")
    sched.submit(v.id, actor="a")  # allowed again once finished
    sched.shutdown()


def test_cancel_stops_between_steps_and_keeps_old_triples(db):
    reg, store, v = prepared(db)
    base_pipeline = BuildPipeline(reg, store, PostgresSource(db))
    base_pipeline.run(v.id)
    before = store.count(v.id)
    started, release = threading.Event(), threading.Event()

    class PausingPipeline(BuildPipeline):
        def _prepare(self):
            started.set()
            release.wait(5)
            super()._prepare()

    sched = BuildScheduler(PausingPipeline(reg, store, PostgresSource(db)), reg)
    run = sched.submit(v.id, actor="a")
    started.wait(5)
    assert sched.cancel(run.id) is True
    release.set()
    done = wait_for(lambda: (r := reg.get_build(run.id)) and r.status != "running" and r)
    assert done.status == "cancelled"
    assert store.count(v.id) == before
    assert sched.cancel(run.id) is False  # nothing left to cancel
    sched.shutdown()


def test_stale_running_runs_are_failed_on_startup(db):
    reg, store, v = prepared(db)
    orphan = reg.start_build(v.id, actor="crashed-process")
    failed = reg.fail_stale_builds(reason="server restarted")
    assert [r.id for r in failed] == [orphan.id]
    assert reg.get_build(orphan.id).status == "failed" and "restarted" in reg.get_build(orphan.id).error


def test_api_build_is_async_by_default_and_wait_is_optional(db):
    seed_tables(db)
    with TestClient(create_app(db=db, settings=ADMIN), headers={"X-Actor": "alice"}) as c:
        c.post("/domains", json={"name": "hr", "base_iri": BASE})
        v = c.post("/domains/hr/versions").json()
        c.put(f"/versions/{v['id']}/ontology", json={"turtle": ontology().to_turtle()})
        c.put(f"/versions/{v['id']}/mapping", json=mapping().to_dict())
        r = c.post(f"/versions/{v['id']}/builds")
        assert r.status_code == 202 and r.json()["status"] == "running"
        run_id = r.json()["id"]
        final = wait_for(lambda: (b := c.get(f"/builds/{run_id}").json()) and b["status"] != "running" and b)
        assert final["status"] == "succeeded"
        r = c.post(f"/versions/{v['id']}/builds", params={"wait": "true"})
        assert r.status_code == 200 and r.json()["status"] == "succeeded"
        assert c.post(f"/builds/{run_id}/cancel").status_code == 409  # already finished
