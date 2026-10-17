#!/usr/bin/env bash
# make report: the facts a session report starts from (AGENTS.md, "Отчёт"). Reads only; a part
# that cannot be read says so instead of failing the rest.
set -uo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root" || exit 1

echo "== git"
git log --oneline -5
git status --short
git diff --stat HEAD
echo "== verify stamp"
python3 scripts/agent_state.py show "$root"
echo "== containers"
docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null || echo "docker unavailable"
echo "== replay"
make --no-print-directory replay-status 2>/dev/null | grep -E 'virtual_now|events_emitted' ||
  echo "virtual_now: не проверено (replay-status failed, Postgres down?)"
