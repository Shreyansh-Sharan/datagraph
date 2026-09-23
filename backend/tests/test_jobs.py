"""Background jobs outlive the process that started them: the table is the record, not a dict."""
import threading
import time
import uuid

import pytest

from ontoforge.jobs import JobRunner
from ontoforge.registry import NotFound, Registry


@pytest.fixture
def env(db):
    reg = Registry(db)
    d = reg.create_domain("jobs", base_iri="http://d/jobs/")
    v = reg.create_version(d.id, actor="alice")
    return reg, v, JobRunner(workers=2, registry=reg, db=db)


def _settled(runner, job_id, timeout=10):
    for _ in range(int(timeout * 50)):
        job = runner.get(job_id)
        if job.status in ("succeeded", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never settled")


def test_a_job_is_readable_from_the_table_by_another_runner(env, db):
    """The screen polling a job may be served by a different worker, or a different process."""
    reg, v, runner = env
    job = runner.submit("profile", v.id, lambda report: (report("halfway"), {"rows": 10})[1], actor="alice", label="s.t")
    done = _settled(runner, job.id)
    assert done.status == "succeeded" and done.result == {"rows": 10}

    other = JobRunner(workers=1, registry=reg, db=db)          # a second instance, sharing nothing but the table
    seen = other.get(job.id)
    assert seen.status == "succeeded" and seen.kind == "profile" and seen.actor == "alice"
    assert seen.label == "s.t" and seen.result == {"rows": 10}


def test_a_failure_is_recorded_with_its_reason(env):
    reg, v, runner = env

    def boom(_report):
        raise ValueError("no such column")

    job = _settled(runner, runner.submit("dq-run", v.id, boom, actor="a").id)
    assert job.status == "failed" and "no such column" in job.error


def test_progress_and_heartbeat_are_written_while_the_job_runs(env):
    reg, v, runner = env
    release = threading.Event()
    job = runner.submit("draft-ontology", v.id, lambda report: (report("reading tables"), release.wait(5))[0], actor="a")
    for _ in range(200):
        if runner.get(job.id).progress == "reading tables":
            break
        time.sleep(0.02)
    live = runner.get(job.id)
    assert live.status == "running" and live.progress == "reading tables" and live.heartbeat_at is not None
    release.set()
    assert _settled(runner, job.id).status == "succeeded"


def test_a_running_job_can_be_cancelled_and_the_work_is_told(env):
    """Cancelling is cooperative: the work polls, stops, and the job ends cancelled, not failed."""
    reg, v, runner = env
    started, stopped = threading.Event(), threading.Event()

    def work(report, should_stop):
        started.set()
        for _ in range(500):
            if should_stop():
                stopped.set()
                return None
            time.sleep(0.01)
        raise AssertionError("never asked to stop")

    job = runner.submit("profile", v.id, work, actor="a")
    assert started.wait(5)
    assert runner.cancel(job.id) is True
    assert stopped.wait(5)
    assert _settled(runner, job.id).status == "cancelled"
    assert runner.cancel(job.id) is False                      # nothing left to cancel


def test_jobs_left_running_by_a_restart_are_failed_at_startup(env, db):
    reg, v, runner = env
    with db.rows() as cur:
        stale = cur.execute(
            "INSERT INTO jobs (kind, version_id, actor, status, progress, started_at, heartbeat_at) "
            "VALUES ('profile', %s, 'a', 'running', 'step 2', now() - interval '1 hour', now() - interval '1 hour') RETURNING id",
            (v.id,)).fetchone()["id"]
    JobRunner(workers=1, registry=reg, db=db).sweep_stale()
    job = runner.get(stale)
    assert job.status == "failed" and "restart" in job.error


def test_the_jobs_of_a_version_are_listed_newest_first(env):
    reg, v, runner = env
    first = _settled(runner, runner.submit("profile", v.id, lambda r: 1, actor="a").id)
    second = _settled(runner, runner.submit("dq-run", v.id, lambda r: 2, actor="a").id)
    listed = runner.list(v.id)
    assert [j.id for j in listed][:2] == [second.id, first.id]
    assert [j.id for j in runner.list(v.id, kind="profile")] == [first.id]
    assert runner.latest(v.id).id == second.id


def test_an_unknown_job_is_not_found(env):
    reg, v, runner = env
    with pytest.raises(NotFound):
        runner.get(uuid.uuid4())
