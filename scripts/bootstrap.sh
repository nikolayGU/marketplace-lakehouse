#!/usr/bin/env bash
# make bootstrap: from a fresh clone with a .env (make secrets) to verified data in bronze and
# silver, protected in Lakekeeper. Safe to re-run: each step checks before it changes anything,
# and none deletes. The first run on the full dataset is long: Spark image build, initial load.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$root/.env" ] || { echo "no .env in $root: run make secrets first" >&2; exit 2; }
. "$root/scripts/chaos/lib.sh"

in_root() { make -C "$ROOT" --no-print-directory "$@"; }

in_root start
for service in spark-bronze kafka-connect trino; do
  wait_until 300 "$service to turn healthy" service_healthy "$service"
done
in_root migrate
bash "$ROOT/connect/register.sh"
if status=$(cd "$ROOT" && PYTHONPATH=oltp .venv/bin/python -m replayer status 2>&1); then
  echo "replay state exists, load skipped"
elif [[ $status == *"no replay state"* ]]; then
  in_root replay-load
else
  printf '%s\n' "$status" >&2
  echo "bootstrap: replayer status failed, output above" >&2
  exit 1
fi
bash "$ROOT/scripts/verify.sh"
# Last: on a fresh stack the silver tables appear only with verify's first silver run.
bash "$ROOT/scripts/lakekeeper/protect.sh"
