"""Structured logging: JSON lines, request timing, request ids, build events."""
import json
import logging

from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.config import Settings
from ontoforge.observability import JsonFormatter, configure_logging
from tests.hr_fixture import BASE

ADMIN = Settings(auth_default_role="admin", log_format="json")


def test_json_formatter_emits_one_object_per_line():
    rec = logging.LogRecord("ontoforge.test", logging.INFO, "f.py", 12, "hello %s", ("world",), None, func="fn")
    rec.request_id = "abc"
    line = JsonFormatter().format(rec)
    obj = json.loads(line)
    assert obj["msg"] == "hello world" and obj["level"] == "INFO" and obj["logger"] == "ontoforge.test"
    assert obj["request_id"] == "abc" and obj["func"] == "fn" and "ts" in obj and "\n" not in line


def test_json_formatter_serialises_exceptions():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        rec = logging.LogRecord("x", logging.ERROR, "f.py", 1, "failed", None, sys.exc_info())
    obj = json.loads(JsonFormatter().format(rec))
    assert "ValueError: boom" in obj["exc"]


def test_configure_logging_switches_formats():
    logger = configure_logging("json")
    assert any(isinstance(h.formatter, JsonFormatter) for h in logger.handlers)
    logger = configure_logging("text")
    assert not any(isinstance(h.formatter, JsonFormatter) for h in logger.handlers)


def test_requests_are_timed_and_carry_request_ids(db, caplog):
    caplog.set_level(logging.INFO, logger="ontoforge.http")
    with TestClient(create_app(db=db, settings=ADMIN), headers={"X-Actor": "alice"}) as c:
        r = c.post("/domains", json={"name": "hr", "base_iri": BASE})
        assert r.status_code == 201
        rid = r.headers["X-Request-ID"]
        assert len(rid) >= 16
        r2 = c.get("/domains/hr", headers={"X-Request-ID": "client-supplied-id"})
        assert r2.headers["X-Request-ID"] == "client-supplied-id"
    records = [x for x in caplog.records if x.name == "ontoforge.http"]
    assert len(records) == 2
    first = records[0]
    assert first.method == "POST" and first.path == "/domains" and first.status == 201
    assert first.duration_ms >= 0 and first.actor == "alice" and first.request_id == rid
    assert records[1].request_id == "client-supplied-id"


def test_health_and_docs_are_not_logged(db, caplog):
    caplog.set_level(logging.INFO, logger="ontoforge.http")
    with TestClient(create_app(db=db, settings=ADMIN)) as c:
        c.get("/health")
        c.get("/openapi.json")
    assert not [x for x in caplog.records if x.name == "ontoforge.http"]


def test_build_lifecycle_is_logged(db, caplog):
    from tests.hr_fixture import seed_tables, ontology, mapping
    caplog.set_level(logging.INFO, logger="ontoforge.build")
    seed_tables(db)
    with TestClient(create_app(db=db, settings=ADMIN), headers={"X-Actor": "alice"}) as c:
        c.post("/domains", json={"name": "hr", "base_iri": BASE})
        v = c.post("/domains/hr/versions").json()
        c.put(f"/versions/{v['id']}/ontology", json={"turtle": ontology().to_turtle()})
        c.put(f"/versions/{v['id']}/mapping", json=mapping().to_dict())
        run = c.post(f"/versions/{v['id']}/builds", params={"wait": "true"}).json()
    events = [(x.event, getattr(x, "run_id", None)) for x in caplog.records if x.name == "ontoforge.build"]
    assert ("build.started", run["id"]) in events and ("build.succeeded", run["id"]) in events
    steps = [x.step for x in caplog.records if x.name == "ontoforge.build" and x.event == "build.step"]
    assert steps == ["compile", "prepare", "load", "finalize"]
