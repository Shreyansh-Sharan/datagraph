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


def test_a_sqlalchemy_style_url_is_accepted_as_pasted():
    """The connection module hands out `postgresql+psycopg://...`; pasting it must just work."""
    from ontoforge.db.connection import normalise_url

    assert normalise_url("postgresql+psycopg://u:p@h:5432/db?sslmode=require") == "postgresql://u:p@h:5432/db?sslmode=require"
    assert normalise_url("postgresql+psycopg2://u@h/db") == "postgresql://u@h/db"
    assert normalise_url("postgres://u@h/db") == "postgres://u@h/db"
    assert normalise_url("postgresql://u@h/db") == "postgresql://u@h/db"


def test_a_live_connection_is_not_checked_on_every_hand_out():
    """Against a managed Postgres a check is a round trip, and one per statement doubles the bill."""
    import time

    from ontoforge.db.connection import idle_check

    checked = []
    check = idle_check(after=0.2, check=lambda conn: checked.append(conn))
    conn = object()
    check(conn)                      # never handed out before: prove it works
    check(conn)                      # straight away again: the last check still stands
    assert len(checked) == 1
    time.sleep(0.25)
    check(conn)                      # idle long enough that it may have been dropped
    assert len(checked) == 2
