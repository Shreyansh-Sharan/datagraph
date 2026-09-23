"""Registry: domains, versions, lifecycle, locking, reviews, build runs, audit."""
from datetime import timedelta

import pytest

from ontoforge.registry import Registry, Status, LifecycleError, LockedError, NotFound


@pytest.fixture
def reg(db):
    return Registry(db)


def test_create_domain_and_first_draft_version(reg):
    d = reg.create_domain("hr", "People and departments", base_iri="http://d/hr/")
    v = reg.create_version(d.id, actor="alice")
    assert (v.version, v.status) == (1, Status.DRAFT)
    assert reg.get_domain("hr").id == d.id
    assert [x.name for x in reg.list_domains()] == ["hr"]


def test_domain_names_are_unique(reg):
    reg.create_domain("hr", base_iri="http://d/")
    with pytest.raises(LifecycleError, match="exists"):
        reg.create_domain("hr", base_iri="http://d/")


def test_only_one_draft_per_domain(reg):
    d = reg.create_domain("hr", base_iri="http://d/")
    reg.create_version(d.id, actor="alice")
    with pytest.raises(LifecycleError, match="draft"):
        reg.create_version(d.id, actor="alice")


def test_content_updates_require_draft_status(reg):
    d = reg.create_domain("hr", base_iri="http://d/")
    v = reg.create_version(d.id, actor="alice")
    reg.update_content(v.id, actor="alice", ontology_ttl="# owl", mapping={"classes": []})
    v = reg.get_version(v.id)
    assert v.ontology_ttl == "# owl" and v.mapping == {"classes": []}
    reg.transition(v.id, Status.IN_REVIEW, actor="alice")
    with pytest.raises(LifecycleError, match="draft"):
        reg.update_content(v.id, actor="alice", ontology_ttl="# changed")


def test_single_editor_lease(reg):
    d = reg.create_domain("hr", base_iri="http://d/")
    v = reg.create_version(d.id, actor="alice")
    reg.acquire_lease(v.id, editor="alice", ttl=timedelta(minutes=10))
    with pytest.raises(LockedError, match="alice"):
        reg.acquire_lease(v.id, editor="bob", ttl=timedelta(minutes=10))
    with pytest.raises(LockedError):
        reg.update_content(v.id, actor="bob", ontology_ttl="x")
    reg.acquire_lease(v.id, editor="alice", ttl=timedelta(minutes=10))  # re-entrant for the holder
    reg.release_lease(v.id, editor="alice")
    reg.acquire_lease(v.id, editor="bob", ttl=timedelta(minutes=10))


def test_expired_lease_can_be_taken_over(reg):
    d = reg.create_domain("hr", base_iri="http://d/")
    v = reg.create_version(d.id, actor="alice")
    reg.acquire_lease(v.id, editor="alice", ttl=timedelta(seconds=-1))
    reg.acquire_lease(v.id, editor="bob", ttl=timedelta(minutes=10))
    assert reg.get_version(v.id).editor == "bob"


def test_admin_takeover_of_active_lease(reg):
    d = reg.create_domain("hr", base_iri="http://d/")
    v = reg.create_version(d.id, actor="alice")
    reg.acquire_lease(v.id, editor="alice", ttl=timedelta(minutes=10))
    reg.acquire_lease(v.id, editor="admin", ttl=timedelta(minutes=10), force=True)
    assert reg.get_version(v.id).editor == "admin"


def test_publish_requires_review_quorum(reg):
    d = reg.create_domain("hr", base_iri="http://d/", review_quorum=2)
    v = reg.create_version(d.id, actor="alice")
    reg.transition(v.id, Status.IN_REVIEW, actor="alice")
    reg.add_review(v.id, reviewer="bob", approved=True, comment="lgtm")
    with pytest.raises(LifecycleError, match="approval"):
        reg.transition(v.id, Status.PUBLISHED, actor="alice")
    reg.add_review(v.id, reviewer="carol", approved=True)
    reg.transition(v.id, Status.PUBLISHED, actor="alice")
    assert reg.get_version(v.id).status == Status.PUBLISHED
    assert reg.latest_version(d.id, status=Status.PUBLISHED).id == v.id


def test_rejection_sends_version_back_to_draft(reg):
    d = reg.create_domain("hr", base_iri="http://d/")
    v = reg.create_version(d.id, actor="alice")
    reg.transition(v.id, Status.IN_REVIEW, actor="alice")
    reg.add_review(v.id, reviewer="bob", approved=False, comment="fix domain/range")
    reg.transition(v.id, Status.DRAFT, actor="alice")
    assert reg.get_version(v.id).status == Status.DRAFT
    assert [r.approved for r in reg.list_reviews(v.id)] == [False]  # append-only history kept


def test_illegal_transitions_are_rejected(reg):
    d = reg.create_domain("hr", base_iri="http://d/")
    v = reg.create_version(d.id, actor="alice")
    with pytest.raises(LifecycleError):
        reg.transition(v.id, Status.PUBLISHED, actor="alice")  # draft -> published skips review
    with pytest.raises(LifecycleError):
        reg.transition(v.id, Status.ARCHIVED, actor="alice")


def test_new_draft_after_publish_copies_content_and_increments_version(reg):
    d = reg.create_domain("hr", base_iri="http://d/")
    v1 = reg.create_version(d.id, actor="alice")
    reg.update_content(v1.id, actor="alice", ontology_ttl="# v1", mapping={"m": 1}, r2rml_ttl="# rr")
    reg.transition(v1.id, Status.IN_REVIEW, actor="alice")
    reg.add_review(v1.id, reviewer="bob", approved=True)
    reg.transition(v1.id, Status.PUBLISHED, actor="alice")
    v2 = reg.create_version(d.id, actor="alice")
    assert (v2.version, v2.status, v2.ontology_ttl, v2.mapping, v2.r2rml_ttl) == (2, Status.DRAFT, "# v1", {"m": 1}, "# rr")
    assert [x.version for x in reg.list_versions(d.id)] == [2, 1]


def test_build_runs_are_recorded(reg):
    d = reg.create_domain("hr", base_iri="http://d/")
    v = reg.create_version(d.id, actor="alice")
    run = reg.start_build(v.id, actor="alice")
    assert run.status == "running"
    reg.finish_build(run.id, status="succeeded", triple_count=42, steps=[{"name": "compile", "seconds": 0.1}])
    run = reg.get_build(run.id)
    assert (run.status, run.triple_count, run.steps[0]["name"]) == ("succeeded", 42, "compile")
    assert run.finished_at is not None
    assert reg.latest_build(v.id).id == run.id


def test_audit_log_records_every_change(reg):
    d = reg.create_domain("hr", base_iri="http://d/")
    v = reg.create_version(d.id, actor="alice")
    reg.update_content(v.id, actor="alice", ontology_ttl="x")
    reg.transition(v.id, Status.IN_REVIEW, actor="alice")
    actions = [e.action for e in reg.audit_trail(v.id)]
    assert actions == ["version.created", "content.updated", "status.in_review"]


def test_missing_ids_raise_not_found(reg):
    import uuid
    with pytest.raises(NotFound):
        reg.get_version(uuid.uuid4())


def test_the_home_screen_reads_every_domain_in_a_handful_of_queries(db):
    """One query per domain is invisible next door and unusable across a region."""
    from ontoforge.registry import Registry, Status

    reg = Registry(db)
    for name in ("a", "b", "c", "d"):
        d = reg.create_domain(name, base_iri=f"http://d/{name}/")
        v1 = reg.create_version(d.id, actor="x")
        reg.transition(v1.id, Status.IN_REVIEW, actor="x")
        reg.add_review(v1.id, reviewer="y", approved=True)
        reg.transition(v1.id, Status.PUBLISHED, actor="x")
        reg.finish_build(reg.start_build(v1.id, actor="x").id, status="succeeded", triple_count=7)
        reg.create_version(d.id, actor="x")

    counted = []
    original = reg._cur

    def counting(*a, **k):
        counted.append(1)
        return original(*a, **k)

    reg._cur = counting
    try:
        cards = reg.cards()
    finally:
        reg._cur = original

    assert len(counted) == 1, f"{len(counted)} transactions for 4 domains"
    assert [c.domain.name for c in cards] == ["a", "b", "c", "d"]
    one = next(c for c in cards if c.domain.name == "a")
    assert len(one.versions) == 2 and one.served.version == 1 and one.latest.version == 2
    assert one.build.triple_count == 7 and one.build.status == "succeeded"
