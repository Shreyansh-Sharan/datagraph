from ontoforge.db import run_migrations, applied_migrations


def test_migrations_apply_and_are_idempotent(db):
    first = applied_migrations(db)
    assert first and first[0].startswith("0001")
    run_migrations(db)  # second run is a no-op
    assert applied_migrations(db) == first


def test_transactions_roll_back_on_error(db):
    with db.transaction() as cur:
        cur.execute("CREATE TABLE t (x int)")
    try:
        with db.transaction() as cur:
            cur.execute("INSERT INTO t VALUES (1)")
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    with db.transaction() as cur:
        assert cur.execute("SELECT count(*) FROM t").fetchone()[0] == 0
