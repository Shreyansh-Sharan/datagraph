"""Every activity becomes a notification: lifecycle and builds through the audit bridge, jobs with their
progress, profiles and rule runs, each visible to the right people, with read state and a since-cursor."""
import time
from datetime import timedelta

from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.build import PostgresSource
from ontoforge.config import Settings
from ontoforge.jobs import JobRunner
from ontoforge.metadata import MetadataService
from ontoforge.notifications import Notifier
from ontoforge.profiling import ProfileService
from ontoforge.registry import Registry, Status
from ontoforge.tabledq import TableQuality
from tests.hr_fixture import seed_tables, BASE


def _reg(db):
    n = Notifier(db)
    reg = Registry(db, notifier=n)
    d = reg.create_domain("hr", base_iri=BASE)
    v = reg.create_version(d.id, actor="alice")
    return n, reg, v


def test_lifecycle_and_build_events_become_notifications_for_the_right_people(db):
    n, reg, v = _reg(db)
    reg.acquire_lease(v.id, editor="alice", ttl=timedelta(minutes=5))
    reg.transition(v.id, Status.IN_REVIEW, actor="alice")
    titles = lambda actor, role: [x["title"] for x in n.feed(actor, role)["items"]]
    assert "hr v1 is ready for review" in titles("bob", "reviewer")                     # reviewers hear it
    assert "hr v1 is ready for review" not in titles("carol", "builder")                 # a builder who is not the actor does not
    assert "hr v1 is ready for review" in titles("alice", "builder")                     # the actor always sees what they caused
    assert "Draft v1 of hr created" in titles("carol", "builder") and "alice took the lease on hr v1" in titles("carol", "builder")
    run = reg.start_build(v.id, actor="alice")
    feed = n.feed("carol", "viewer")
    row = next(x for x in feed["items"] if x["kind"] == "build.started")
    assert row["status"] == "running" and row["link"]["screen"] == "build" and row["domain"] == "hr" and row["version"] == 1
    n.progress(("build", str(run.id)), "step 3 of 7: plan")
    assert next(x for x in n.feed("carol", "viewer")["items"] if x["id"] == row["id"])["progress"] == "step 3 of 7: plan"
    reg.finish_build(run.id, status="succeeded", triple_count=1234)
    done = next(x for x in n.feed("carol", "viewer")["items"] if x["id"] == row["id"])
    assert done["status"] == "done" and done["title"] == "Build of hr v1 succeeded" and done["body"] == "1,234 triples" and done["progress"] is None
    assert sum(1 for x in n.feed("carol", "viewer")["items"] if x["kind"].startswith("build.")) == 1   # start and finish share one row


def test_read_state_and_the_since_cursor(db):
    n, reg, v = _reg(db)
    reg.add_comment(v.id, author="alice", body="hello")
    reg.add_comment(v.id, author="alice", body="again")
    feed = n.feed("bob", "viewer")
    assert feed["unread"] == 3 and all(not x["read"] for x in feed["items"])
    n.mark_read("bob", ids=[feed["items"][0]["id"]])
    feed = n.feed("bob", "viewer")
    assert feed["unread"] == 2 and feed["items"][0]["read"] is True and feed["items"][1]["read"] is False
    n.mark_read("bob", until=feed["latest_id"])
    assert n.feed("bob", "viewer")["unread"] == 0 and n.feed("alice", "viewer")["unread"] == 3   # per person
    run = reg.start_build(v.id, actor="alice")
    later = n.feed("bob", "viewer", since=feed["latest_id"])
    assert [x["kind"] for x in later["items"]] == ["build.started"] and later["unread"] == 1
    reg.finish_build(run.id, status="failed", error="boom")
    assert next(x for x in n.feed("bob", "viewer")["items"] if x["kind"] == "build.started")["status"] == "failed"


def test_jobs_profiles_and_rule_runs_announce_themselves(db):
    seed_tables(db)
    n, reg, v = _reg(db)
    src = PostgresSource(db)
    meta = MetadataService(reg, src.catalog, db); meta.notifier = n
    meta.import_tables(v.id, ["employees"], actor="alice")
    assert any(x["kind"] == "metadata.imported" and "1 table snapshotted" in x["title"] for x in n.feed("bob", "viewer")["items"])
    jobs = JobRunner(workers=1, notifier=n, registry=reg)
    seen = []

    def work(report):
        report("Describing table 1 of 2"); time.sleep(1.1); report("Describing table 2 of 2"); seen.append(1); return {"ok": True}
    job = jobs.submit("profile", v.id, work, actor="alice", label="employees")
    for _ in range(50):
        if job.status != "running": break
        time.sleep(0.1)
    row = next(x for x in n.feed("bob", "viewer")["items"] if x["kind"] == "job.profile")
    assert row["status"] == "done" and row["title"] == "Profiled employees" and row["link"] == {"screen": "table", "tab": "profile", "domain": "hr", "version": 1, "table": "employees"}
    failing = jobs.submit("dq-run", v.id, lambda report: (_ for _ in ()).throw(RuntimeError("no source")), actor="alice", label="employees")
    for _ in range(50):
        if failing.status != "running": break
        time.sleep(0.1)
    bad = next(x for x in n.feed("bob", "viewer")["items"] if x["kind"] == "job.dq-run")
    assert bad["status"] == "failed" and "no source" in (bad["body"] or "")
    profiles = ProfileService(reg, meta, src, db); profiles.notifier = n
    profiles.run(v.id, "employees", actor="alice")
    assert any(x["kind"] == "profile.run" and x["title"] == "Profiled employees: 4 rows" for x in n.feed("bob", "viewer")["items"])
    dq = TableQuality(reg, meta, src, db); dq.notifier = n
    dq.add_rule(v.id, "employees", actor="alice", name="Salary present", column="sal", kind="not_null")
    dq.run(v.id, "employees", actor="alice")
    items = n.feed("bob", "viewer")["items"]
    assert any(x["kind"] == "dq.rule.added" and "Salary present" in x["title"] for x in items)
    ran = next(x for x in items if x["kind"] == "dq.run")
    assert ran["status"] == "done" and ran["title"].startswith("Rules of employees ran: 75%") and ran["link"]["tab"] == "dq"


def test_the_feed_is_served_over_the_api_and_the_restart_sweep_fails_running_jobs(db):
    app = create_app(db=db, source_db=db, settings=Settings(auth_default_role="admin"))
    with TestClient(app, headers={"X-Actor": "alice"}) as c:
        c.post("/domains", json={"name": "hr", "description": "People", "base_iri": BASE})
        c.post("/domains/hr/versions")
        feed = c.get("/notifications").json()
        assert feed["unread"] >= 1 and any(x["title"] == "Draft v1 of hr created" for x in feed["items"])
        assert c.post("/notifications/read", json={"until": feed["latest_id"]}).json()["unread"] == 0
        assert c.get("/notifications", params={"since": feed["latest_id"]}).json()["items"] == []
    n = app.state.notifier
    n.emit(None, "job.profile", title="Profiling x", status="running", ref=("job", "left-over"))
    again = create_app(db=db, source_db=db, settings=Settings(auth_default_role="admin"))   # a new process over the same database
    with TestClient(again, headers={"X-Actor": "alice"}) as c:                                  # its lifespan sweeps what the old one left running
        row = next(x for x in c.get("/notifications").json()["items"] if x["kind"] == "job.profile")
        assert row["status"] == "failed" and "restarted" in row["body"]
