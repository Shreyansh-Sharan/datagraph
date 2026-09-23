#!/usr/bin/env bash
# Stop the locally started API (leaves Postgres running; `docker stop ontoforge-pg` to stop it too).
pkill -f "ontoforge serve" && echo "[ontoforge] stopped" || echo "[ontoforge] not running"
