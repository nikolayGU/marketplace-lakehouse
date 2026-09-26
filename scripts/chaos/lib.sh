#!/usr/bin/env bash
# Helpers for scripts/chaos/*.sh. Sourced, not run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
set -a
# shellcheck source=/dev/null
. "$ROOT/.env"
set +a
COMPOSE=(docker compose --env-file "$ROOT/.env" -f "$ROOT/docker/compose.yaml")

# Aligned table for people, bare values for scripts.
trino() { "${COMPOSE[@]}" exec -T trino trino --catalog lake --output-format ALIGNED --execute "$1"; }
trino_value() { "${COMPOSE[@]}" exec -T trino trino --catalog lake --output-format TSV --execute "$1"; }
psql_value() { "${COMPOSE[@]}" exec -T postgres-oltp psql -U "$OLTP_USER" -d "$OLTP_DB" -Atc "$1"; }
kafka() { "${COMPOSE[@]}" exec -T kafka "/opt/kafka/bin/$1" --bootstrap-server localhost:9092 "${@:2}"; }

# wait_until <seconds> <what> <command...>: run the command every 3 s until it succeeds. On a
# timeout the last attempt's error output is shown, since that is usually the real cause.
wait_until() {
  local limit=$1 what=$2 err=""
  local deadline=$((SECONDS + limit))
  shift 2
  until err=$("$@" 2>&1 >/dev/null); do
    if ((SECONDS >= deadline)); then
      echo "timed out after $limit s waiting for $what${err:+: $err}" >&2
      return 1
    fi
    sleep 3
  done
}

# Silent on success. The container is removed on exit, so the log is kept in a file and its
# path printed with the last lines when the run fails.
run_silver() {
  local log
  log=$(mktemp -t silver_upsert.XXXXXX.log)
  if ! make -C "$ROOT" --no-print-directory silver >"$log" 2>&1; then
    tail -40 "$log" >&2
    echo "silver_upsert failed, full log: $log" >&2
    return 1
  fi
  rm -f "$log"
}
