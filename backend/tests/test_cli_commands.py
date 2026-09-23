import subprocess
import sys
import uuid

from ontoforge.cli import main
from ontoforge.db import Database, applied_migrations
from tests.conftest import TEST_DATABASE_URL


def test_migrate_command_applies_migrations(capsys):
    schema = "cli_" + uuid.uuid4().hex[:10]
    db = Database(TEST_DATABASE_URL, schema=schema)
    with db.transaction() as cur:
        cur.execute(f'CREATE SCHEMA "{schema}"')
    try:
        assert main(["migrate", "--database-url", TEST_DATABASE_URL, "--schema", schema]) == 0
        out = capsys.readouterr().out
        assert "0001" in out and "0002" in out
        assert len(applied_migrations(db)) >= 2
        assert main(["migrate", "--database-url", TEST_DATABASE_URL, "--schema", schema]) == 0
        assert "up to date" in capsys.readouterr().out
    finally:
        with db.transaction() as cur:
            cur.execute(f'DROP SCHEMA "{schema}" CASCADE')
        db.close()


def test_help_lists_all_commands():
    r = subprocess.run([sys.executable, "-m", "ontoforge", "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    for cmd in ("compile", "migrate", "serve", "serve-mcp"):
        assert cmd in r.stdout
