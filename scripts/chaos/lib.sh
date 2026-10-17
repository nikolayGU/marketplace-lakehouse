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

healthy() { [ "$(docker inspect -f '{{.State.Health.Status}}' "$1" 2>/dev/null)" = healthy ]; }

# service_healthy <service>: the container of a compose service reports healthy. Looked up by id,
# so it works under any COMPOSE_PROJECT_NAME (a fresh clone runs as lakehouse-fresh).
service_healthy() {
  local id
  id=$("${COMPOSE[@]}" --profile '*' ps -q "$1") && [ -n "$id" ] && healthy "$id"
}

# replay_burst <real seconds> [VAR=value ...]: play the schedule on the host, then stop. The
# replayer resumes from its saved virtual clock, so a burst spends only what it plays. It never
# exits by itself, so any status but timeout's 124 is a failure and shows the log tail.
# --foreground keeps timeout in the caller's process group, so a script that runs the burst as a
# job of its own group stops all of it with one kill.
replay_burst() {
  local seconds=$1 rc=0 log
  shift
  log=$(mktemp -t replay_burst.XXXXXX.log)
  (cd "$ROOT" && env REPLAY_SPEED="${CHAOS_REPLAY_SPEED:-720}" "$@" PYTHONPATH=oltp \
    timeout --foreground "$seconds" .venv/bin/python -m replayer start >"$log" 2>&1) || rc=$?
  if [ "$rc" -ne 124 ]; then
    tail -20 "$log" >&2
    echo "replayer exited $rc, full log: $log" >&2
    return 1
  fi
  rm -f "$log"
}

# The replayer's virtual clock; fails when there is no replay state (`replayer status` exits 1).
virtual_now() {
  (cd "$ROOT" && PYTHONPATH=oltp .venv/bin/python -m replayer status) |
    python3 -c 'import json, sys; print(json.load(sys.stdin)["virtual_now"])'
}

# Returns 2, so a script under set -e stops with 2 before it touches anything.
no_other_replayer() {
  if curl -sf -o /dev/null --max-time 2 http://127.0.0.1:8000/health; then
    echo "a replayer already answers on :8000 (oltp-replayer or make replay-start); stop it" \
      "first: the burst cannot bind the port and that replayer keeps playing at REPLAY_SPEED" >&2
    return 2
  fi
}

# Every record of the CDC topics is in bronze: the end offset of each non-empty partition equals
# bronze's highest offset there plus one. A failed or empty Kafka listing counts as not caught up.
kafka_ends() {
  kafka kafka-get-offsets.sh --topic 'oltp\.shop\..*' --time -1 | awk -F: '$3 > 0' | sort
}
bronze_ends() {
  trino_value "select topic || ':' || cast(kafka_partition as varchar) || ':'
                      || cast(max(kafka_offset) + 1 as varchar)
               from bronze.cdc_events group by topic, kafka_partition" | sort
}
bronze_caught_up() {
  local k b
  k=$(kafka_ends) && [ -n "$k" ] && b=$(bronze_ends) || return 1
  [ -z "$(comm -23 <(printf '%s\n' "$k") <(printf '%s\n' "$b"))" ]
}

# Per topic partition: copies of one offset, and holes between the lowest and highest offset.
bronze_offsets_report() {
  trino "select topic, kafka_partition, count(*) - count(distinct kafka_offset) as duplicates,
                max(kafka_offset) - min(kafka_offset) + 1 - count(distinct kafka_offset) as missing
         from bronze.cdc_events group by 1, 2 order by 1, 2"
}

# bronze_offsets_report for scripts: 1 when some topic partition holds an offset twice or misses
# one between its lowest and highest offset, 2 when the query fails.
bronze_offsets_ok() {
  local bad
  bad=$(trino_value "select count(*) from (
                       select 1 from bronze.cdc_events group by topic, kafka_partition
                       having count(*) > count(distinct kafka_offset)
                          or max(kafka_offset) - min(kafka_offset) + 1
                            > count(distinct kafka_offset))") || return 2
  [ "$bad" = 0 ]
}

connector_running() {
  curl -sf http://127.0.0.1:8083/connectors/shop-connector/status | python3 -c '
import json, sys
d = json.load(sys.stdin)
running = d["connector"]["state"] == "RUNNING"
sys.exit(not (running and d["tasks"] and all(t["state"] == "RUNNING" for t in d["tasks"])))'
}

# slot_reattached <pid>: a walsender other than <pid> streams shop_slot. After a kill,
# connect-status can still hold the dead worker's RUNNING records; Postgres cannot.
slot_reattached() {
  [ "$(psql_value "select active and active_pid <> $1 from pg_replication_slots
                   where slot_name = 'shop_slot'")" = t ]
}

# Every silver contract, Postgres against silver's live rows: row count, md5 of the sorted
# primary keys, and the sum of each decimal column (scripts/reconcile_sql.py). 1 when any table
# differs, 2 when a query fails. Counts alone miss a lost row that an undeleted one offsets.
reconcile() {
  local t pg_sql lake_sql pg lake sql status=0
  local -a p l
  sql=$(python3 "$ROOT/scripts/reconcile_sql.py" "$ROOT/contracts/silver") || return 2
  # fd 3: docker compose exec inside the loop would otherwise read the remaining lines.
  while IFS=$'\t' read -r -u 3 t pg_sql lake_sql; do
    pg=$(psql_value "$pg_sql") || return 2
    lake=$(trino_value "$lake_sql") || return 2
    read -r -a p <<<"$pg"
    read -r -a l <<<"$lake"
    printf '%-12s postgres %8s  silver %8s  rows %-4s keys %-4s sums %s\n' "$t" "${p[0]}" \
      "${l[0]}" "$([ "${p[0]}" = "${l[0]}" ] && echo ok || echo DIFF)" \
      "$([ "${p[1]}" = "${l[1]}" ] && echo ok || echo DIFF)" \
      "$(if [ ${#p[@]} -eq 2 ]; then echo -; elif [ "${p[*]:2}" = "${l[*]:2}" ]; then
           echo "ok (${p[*]:2})"; else echo "DIFF (postgres ${p[*]:2}, silver ${l[*]:2})"; fi)"
    [ "$pg" = "$lake" ] || status=1
  done 3<<<"$sql"
  return "$status"
}

# Events bronze holds more than once with the same LSN, ingested since <utc 'YYYY-MM-DD HH:MM:SS'>.
# Both copies must be ingested after that time: after a Connect kill the first copy can be up to
# offset.flush.interval.ms (60 s) older than the kill, so start the window before that.
lsn_duplicates_since() {
  trino "select source_table, count(distinct key) as keys_repeated, count(*) as events_repeated,
                sum(copies - 1) as extra_events
         from (select source_table, key, lsn, count(*) as copies from bronze.cdc_events
               where ingest_ts >= timestamp '$1' and lsn is not null
               group by 1, 2, 3 having count(*) > 1)
         group by 1 order by 1"
}
