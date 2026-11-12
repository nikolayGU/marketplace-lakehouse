#!/usr/bin/env bash
# One-shot setup of Superset, safe to repeat: metadata migration, admin user, roles and the
# Marketplace dashboard bundle: the database, and the datasets (columns, metrics), charts and
# dashboard, which the bundle overwrites by uuid on every run (UI edits to them are lost).
set -euo pipefail

BUNDLE_DIR="${BUNDLE_DIR:-/bundle}"

superset db upgrade

# create-admin on an existing user prints "Error! User already exists" and exits 0, so the
# check only keeps the log clean; an empty password would create an admin nobody can log in as.
: "${SUPERSET_ADMIN_PASSWORD:?}"
if superset fab list-users | grep -q "username:admin |"; then
  echo "admin exists"
else
  superset fab create-admin \
    --username admin --firstname Admin --lastname Admin \
    --email admin@localhost --password "${SUPERSET_ADMIN_PASSWORD}"
fi

superset init

# Importing a database makes Superset list the catalogs of Trino, so the import needs Trino up
# (profile query). Without it the dashboard is skipped; run this service again once Trino is up.
if ! python -c 'import json, sys, urllib.request
info = json.load(urllib.request.urlopen(sys.argv[1], timeout=5))
sys.exit(1 if info.get("starting", True) else 0)' \
  "${TRINO_INFO_URL:-http://trino:8080/v1/info}"; then
  echo "WARNING: Trino is not reachable, dashboard import skipped" >&2
  exit 0
fi

python /init/import_bundle.py "$BUNDLE_DIR"
