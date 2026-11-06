#!/usr/bin/env bash
# One-shot setup of Superset, safe to repeat: metadata migration, admin user, roles and the
# Marketplace dashboard bundle (database, datasets, charts, dashboard, matched by uuid).
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

archive="$(mktemp --suffix .zip)"
trap 'rm -f "$archive"' EXIT
python - "$BUNDLE_DIR" "$archive" <<'PY'
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

source, target = Path(sys.argv[1]), Path(sys.argv[2])
# The importer drops the first path component of every entry, so the files go under one root.
with ZipFile(target, "w", ZIP_DEFLATED) as bundle:
    for path in sorted(source.rglob("*")):
        if path.is_file():
            bundle.write(path, Path("marketplace") / path.relative_to(source))
PY
superset import-dashboards -p "$archive" -u admin
