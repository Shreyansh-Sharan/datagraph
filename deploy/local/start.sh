#!/usr/bin/env bash
# Run datagraph on this machine: Postgres in Docker, the demo schema with sample tables, the API.
# Usage: deploy/local/start.sh [--open]   env: ONTOFORGE_PORT (default 8765), ONTOFORGE_SCHEMA (default demo)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PORT="${ONTOFORGE_PORT:-8765}"

# .env decides where the registry lives, so pointing it at a managed Postgres is all it takes to
# move this machine over. Only when nothing names one is the local container the answer.
from_env() { sed -n "s/^$1=//p" .env 2>/dev/null | head -1 | tr -d "\"' "; }
URL="${ONTOFORGE_DATABASE_URL:-$(from_env ONTOFORGE_DATABASE_URL)}"
if [ -z "$URL" ]; then
  URL="postgresql://ontoforge:ontoforge@localhost:5439/ontoforge"
  export ONTOFORGE_DATABASE_URL="$URL"
fi
case "$URL" in *localhost:5439*|*127.0.0.1:5439*) LOCAL_DB=yes;; *) LOCAL_DB=no;; esac
SCHEMA="${ONTOFORGE_SCHEMA:-$(from_env ONTOFORGE_DATABASE_SCHEMA)}"
SCHEMA="${SCHEMA:-demo}"
export ONTOFORGE_AUTH_DEFAULT_ROLE="${ONTOFORGE_AUTH_DEFAULT_ROLE:-admin}"   # local trial: everyone is admin
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

log() { printf '[datagraph] %s\n' "$*"; }

# 1. Postgres (the same container deploy/compose.dev.yml starts, so either way works). A registry
#    that lives somewhere else needs no container here.
if [ "$LOCAL_DB" = no ]; then
  log "registry is remote; not starting the local Postgres"
elif ! (docker ps --format '{{.Names}}' | grep -qx ontoforge-pg); then
  if docker ps -a --format '{{.Names}}' | grep -qx ontoforge-pg; then docker start ontoforge-pg >/dev/null
  else docker run -d --name ontoforge-pg -e POSTGRES_USER=ontoforge -e POSTGRES_PASSWORD=ontoforge -e POSTGRES_DB=ontoforge -p 5439:5432 postgres:16-alpine >/dev/null; fi
fi
if [ "$LOCAL_DB" = yes ]; then
  for _ in $(seq 1 60); do docker exec ontoforge-pg pg_isready -U ontoforge >/dev/null 2>&1 && break; sleep 1; done
  log "postgres ready (container ontoforge-pg, port 5439)"
fi

# 2. Python environment
[ -x .venv/bin/python ] || { log "creating .venv"; uv venv -q && uv pip install -q -e "./backend[dev]"; }

# 3. Schema, migrations, sample data (idempotent)
.venv/bin/python - "$SCHEMA" <<'PY'
import sys
from ontoforge.config import load_settings
from ontoforge.db import Database, run_migrations
schema = sys.argv[1]
db = Database(load_settings().database_url, schema=schema)
with db.transaction() as cur:
    cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    has_tables = cur.execute("SELECT to_regclass(%s)", (f"{schema}.employees",)).fetchone()[0]
run_migrations(db)
if schema == "demo" and not has_tables:
    sys.path.insert(0, ".")
    from tests.backend.hr_fixture import seed_tables
    seed_tables(db)
    with db.transaction() as cur:
        cur.execute("COMMENT ON COLUMN employees.sal IS 'Monthly salary in EUR'")
    print("[datagraph] seeded sample HR tables into schema demo")
db.close()
PY

# 4. Serve
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then log "port $PORT is already in use — set ONTOFORGE_PORT"; exit 1; fi
# The app is frontend/, served by its own dev server. This API serves it only when a build is
# configured, so point the browser at whichever one is actually there.
if [ -n "${ONTOFORGE_UI_DIR:-}" ]; then WHERE="http://127.0.0.1:$PORT/ui/"; else WHERE="http://127.0.0.1:$PORT/docs"; fi
log "API: http://127.0.0.1:$PORT   docs: /docs   MCP: /mcp   (schema $SCHEMA, default role $ONTOFORGE_AUTH_DEFAULT_ROLE)"
[ -z "${ONTOFORGE_UI_DIR:-}" ] && log "UI: run 'make ui' for the dev server on http://127.0.0.1:5173/ui/"
[ "${1:-}" = "--open" ] && (sleep 2; open "$WHERE") &
exec .venv/bin/python -m ontoforge serve --host 127.0.0.1 --port "$PORT" --schema "$SCHEMA"
