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
echo "== stamps"
for kind in verify check review; do
  shown="$(python3 scripts/agent_state.py show "$kind" "$root" 2>/dev/null || echo unreadable)"
  echo "$kind: $shown"
done
echo "== containers"
docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null || echo "docker unavailable"
# REL-01: docker ps does not show a container that is down. After `docker kill` or `docker stop`
# restart: unless-stopped leaves it down, and nothing else raises it. One-shot jobs (restart "no")
# are meant to exit and are not listed. Only name, policy, state and exit code are read, no Env.
# The project is COMPOSE_PROJECT_NAME of this shell, as `docker compose` reads it, else lakehouse.
stopped_containers() {
  local project="${COMPOSE_PROJECT_NAME:-lakehouse}"
  local label="label=com.docker.compose.project=$project"
  local format='{{.Name}} {{.HostConfig.RestartPolicy.Name}}'
  format+=' {{.State.Status}} {{.State.ExitCode}}'
  local ids_text info="" name policy state code down=0
  local -a ids
  ids_text="$(docker ps -aq --filter "$label" 2>/dev/null)" || return 1
  echo "project: $project"
  if [ -z "$ids_text" ]; then
    echo "no containers of project $project"
    return 0
  fi
  mapfile -t ids <<<"$ids_text"
  info="$(docker inspect --format "$format" "${ids[@]}" 2>/dev/null)" || return 1
  while read -r name policy state code; do
    case "$policy" in unless-stopped | always) ;; *) continue ;; esac
    [ "$state" = running ] && continue
    echo "${name#/} $state (exit $code, restart: $policy)"
    down=1
  done <<<"$info"
  if [ "$down" = 1 ]; then
    echo "restart: unless-stopped does not raise a container that docker kill or docker stop"
    echo "stopped; raise it with: docker start <name> (needs the owner's ok)"
  else
    echo "all restartable containers run"
  fi
}
echo "== stopped containers"
stopped_containers || echo "docker unavailable"
echo "== replay"
make --no-print-directory replay-status 2>/dev/null | grep -E 'virtual_now|events_emitted' ||
  echo "virtual_now: не проверено (replay-status failed, Postgres down?)"
