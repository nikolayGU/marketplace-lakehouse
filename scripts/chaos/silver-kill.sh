#!/usr/bin/env bash
# Chaos 10b: kill the silver merge between two tables (OPERATIONS.md, scenario 10b). The three DAGs
# that touch silver are paused, a burst piles up events in bronze, then silver_upsert is unpaused
# and `lakehouse-silver-merge` is killed once its log shows a table merged. No manual trigger: the
# scheduler creates the run itself, at once for the interval missed while paused or on the next */5
# border, so the wait is up to 6 minutes. The merge goes through the tables one after another, so
# silver is then part new, part old; the retry of the task must bring it level with Postgres without
# a duplicate or a lost row. Needs orchestrate up and no replay. A container left behind by the kill
# is never removed here: that is the owner's call.
. "$(dirname "$0")/lib.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }

merge=lakehouse-silver-merge
burst_seconds=${SILVER_KILL_BURST:-30}
dags=(silver_upsert dbt_build dq_checks)
paused_by_me=()
burst=""

merge_container() { docker ps -a --filter "name=^/$merge\$" -q; }
# Airflow 3 prints the pause flag of `dags list -o json` as the string "True" or "False".
# Attempts of a task are not in the CLI (`tasks states-for-dag-run` has no try_number), so the
# retry is proved through the REST API of the api-server, as task_log in lib.sh does: no login
# (D12), /auth/token hands out a token, the task instance carries state and try_number.
api_get() {
  local api="http://${BIND_IP:-127.0.0.1}:8090" token
  token=$(curl -sf "$api/auth/token" | python3 -c 'import json, sys; print(json.load(sys.stdin)["access_token"])') || return 1
  curl -sf -H "Authorization: Bearer $token" "$api/api/v2/$1"
}
# "<run_id> <state>" per running or queued run of silver_upsert, through the REST API.
active_runs() {
  api_get "dags/silver_upsert/dagRuns?state=running&state=queued&limit=50" | python3 -c '
import json, sys
for r in json.load(sys.stdin)["dag_runs"]:
    print(r["dag_run_id"], r["state"])'
}
merge_task_instance() {
  api_get "dags/silver_upsert/dagRuns/$1/taskInstances/merge" | python3 -c '
import json, sys
t = json.load(sys.stdin)
print(t["state"], t["try_number"])'
}
merged_lines() { { docker logs "$merge" 2>&1 || true; } | grep 'events merged into lake.silver.' || true; }
diff_tables() { grep -c DIFF <<<"$1" || true; }
stop_burst() { [ -z "$burst" ] || kill -TERM -- -"$burst" 2>/dev/null || true; }
# Only the DAGs this script paused are unpaused again; a DAG that was paused before stays so.
cleanup() {
  stop_burst
  local d
  for d in ${paused_by_me[@]+"${paused_by_me[@]}"}; do
    airflow_cli dags unpause "$d" >/dev/null || echo "could not unpause $d: do it by hand" >&2
  done
}

no_other_replayer
[ -n "$("${COMPOSE[@]}" --profile '*' ps -q airflow-scheduler)" ] ||
  fail "airflow-scheduler is not running: the merge of this scenario is the silver_upsert DAG"
left=$(merge_container)
[ -z "$left" ] ||
  fail "a container $merge exists ($(docker ps -a --filter "name=^/$merge\$" \
    --format '{{.Status}}')): a merge is running or a leftover blocks the next one (409, see" \
    "OPERATIONS.md, Timeouts); nothing was changed"

states=$(airflow_cli dags list -o json 2>/dev/null | python3 -c '
import json, sys
lines = sys.stdin.read().splitlines()
start = next(i for i, line in enumerate(lines) if line.strip() == "[" or line.lstrip().startswith("[{"))
for d in json.loads("\n".join(lines[start:])):
    if d["dag_id"] in sys.argv[1:]:
        print(d["dag_id"], "paused" if str(d["is_paused"]).lower() == "true" else "active")' "${dags[@]}") ||
  fail "could not read the state of the DAGs"
[ "$(wc -l <<<"$states")" -eq "${#dags[@]}" ] || fail "not all of ${dags[*]} exist: $states"

! grep -qx "silver_upsert paused" <<<"$states" ||
  fail "silver_upsert is paused already: unpause it first, this run needs the scheduler to start it"
trap cleanup EXIT
for d in "${dags[@]}"; do
  if grep -qx "$d active" <<<"$states"; then
    airflow_cli dags pause "$d" >/dev/null || fail "could not pause $d"
    paused_by_me+=("$d")
  fi
done
echo "paused by this run: ${paused_by_me[*]:-none} (the others were paused already)"

quarantine_before=$(trino_value "select count(*) from silver.quarantine")
echo "silver.quarantine before the burst: $quarantine_before rows"

# The burst runs in a process group of its own, so an early exit or ctrl-c stops all of it.
set -m
replay_burst "$burst_seconds" &
burst=$!
set +m
wait "$burst" || fail "the replay burst failed; its log is above"
burst=""
wait_until 300 "bronze to catch up with Kafka" bronze_caught_up
# Debezium may still hold the tail of the burst: let it land, so the final reconcile is not early.
# The settle and the second catch-up depend on the live Debezium and bronze: the unit test runs
# them with no wait against a fake, so only a live run shows that the pause is long enough.
sleep "${SILVER_KILL_SETTLE:-10}"
wait_until 300 "bronze to catch up with Kafka" bronze_caught_up

rc=0
before=$(reconcile) || rc=$?
echo "$before"
[ "$rc" -ne 2 ] || fail "reconcile could not run before the merge"
with_events=$(diff_tables "$before")
[ "$with_events" -gt 0 ] || fail "burst brought nothing to merge: silver already equals Postgres"
echo "$with_events tables differ from Postgres before the merge"

airflow_cli dags unpause silver_upsert >/dev/null || fail "could not unpause silver_upsert"
echo "unpaused silver_upsert at $(date -u +%T): waiting for the run the scheduler creates"

# Step 1, the run: which run is it. REST only, and not in the hot loop below. silver_upsert has
# max_active_runs=1 and catchup=False (airflow/dags/silver_upsert.py), so while this run is active
# no second one is running, and the scheduler makes at most the one run of the missed interval.
# Two runs seen, or a queued one besides, means the merge on screen may not be this run's.
limit=${SILVER_KILL_START_WAIT:-360}
deadline=$((SECONDS + limit))
run=""
while [ -z "$run" ]; do
  active=$(active_runs) || active=""
  if [ -n "$active" ]; then
    if [ "$(grep -c . <<<"$active")" -ne 1 ] || ! grep -q ' running$' <<<"$active"; then
      fail "inconclusive: another run of silver_upsert is running or queued, or the run is not" \
        "running yet (${active//$'\n'/; }); nothing was killed, run again"
    fi
    run=${active%% *}
  elif ((SECONDS >= deadline)); then
    fail "no run of silver_upsert started within $limit s after the unpause (scheduler down or" \
      "the DAG is held back); nothing was killed"
  else
    sleep 1
  fi
done
echo "silver_upsert run $run is running at $(date -u +%T)"

# Step 2, the kill: the hot loop calls only `docker logs` (about a tenth of a second, no airflow
# CLI and no REST, which cost 3 s each) and kills at once on the first merged table: the window
# from the first to the last table is 4 to 11 s. Polling every 0.2 s beats `logs -f | grep -m1`
# here: that pipe leaves a docker logs process behind until the next log line and cannot be
# stopped by the deadline. A log that is not there yet (the task has not started the container)
# just means keep looking; one that was there and went away means the merge ended.
seen=""
lines=""
while :; do
  if out=$(docker logs "$merge" 2>&1); then
    seen=1
    lines=$(grep 'events merged into lake.silver.' <<<"$out" || true)
    [ -z "$lines" ] || break
  elif [ -n "$seen" ]; then
    fail "inconclusive: the merge ended before a table was seen, nothing was killed, run again"
  fi
  if ((SECONDS >= deadline)); then
    fail "no running $merge with a merged table within $limit s;" \
      "the merge may have ended before the kill (inconclusive, run again)"
  fi
  sleep 0.2
done
docker kill "$merge" >/dev/null ||
  fail "inconclusive: the merge ended before the kill, run again ($merge was gone or not running)"
killed_at=$(date -u +%T)
# The log as it is after the kill; the lines seen before it stay when the container is gone.
after=$(merged_lines)
[ -z "$after" ] || lines=$after
merged=$(sed -n 's/.*events merged into lake\.silver\.\([a-z_]*\).*/\1/p' <<<"$lines" | sort -u | wc -l)
echo "killed $merge at $killed_at: $merged of $with_events tables with events were merged"
echo "$lines"

rc=0
partial=$(reconcile) || rc=$?
echo "$partial"
[ "$rc" -ne 2 ] || fail "reconcile could not run after the kill"
echo "$(diff_tables "$partial") tables differ from Postgres right after the kill (partial state)"
[ "$rc" -ne 0 ] ||
  fail "inconclusive: the kill came after the last table with events (silver already equals" \
    "Postgres, no partial state), run again"

deadline=$((SECONDS + ${SILVER_KILL_WAIT:-600}))
while :; do
  state=$(dag_run_state silver_upsert "$run") || state=unknown
  case $state in success | failed) break ;; esac
  if ((SECONDS >= deadline)); then
    fail "silver_upsert run $run is still $state after ${SILVER_KILL_WAIT:-600} s"
  fi
  sleep "${SILVER_KILL_POLL:-5}"
done
echo "silver_upsert run $run ended $state at $(date -u +%T)"
left=$(merge_container)
if [ -n "$left" ]; then
  fail "$merge is still there ($(docker ps -a --filter "name=^/$merge\$" \
    --format '{{.Status}}')) after the run ended: the 409 case, every next merge fails with" \
    "\"name is already in use\". Not removed here: see OPERATIONS.md, Timeouts; docker rm only" \
    "with the owner's ok."
fi

problems=()
[ "$state" = success ] || problems+=("dag run $run ended $state")
rc=0
final=$(reconcile) || rc=$?
echo "$final"
[ "$rc" -eq 0 ] || problems+=("reconcile is not 7/7 after the retry (status $rc)")
bronze_offsets_ok || problems+=("a Kafka offset is in bronze twice or missing")
if quarantine_after=$(trino_value "select count(*) from silver.quarantine"); then
  [ "$quarantine_after" -le "$quarantine_before" ] ||
    problems+=("silver.quarantine grew from $quarantine_before to $quarantine_after rows")
else
  problems+=("could not read silver.quarantine after the retry")
fi
if remembered=$(airflow_cli variables get silver_upsert_last_bronze_snapshot | tail -n 1 | tr -d '\r') &&
  latest=$(trino_value 'select snapshot_id from bronze."cdc_events$snapshots"
                        order by committed_at desc limit 1'); then
  [ "$remembered" = "$latest" ] ||
    problems+=("LAST_BRONZE_SNAPSHOT is $remembered, the last bronze snapshot is $latest")
else
  problems+=("could not read LAST_BRONZE_SNAPSHOT or the last bronze snapshot")
fi
# The killed attempt fails the task, Airflow retries it: the merge of this very run is a success
# with more than one attempt.
if ti=$(merge_task_instance "$run"); then
  read -r ti_state ti_tries <<<"$ti"
  [ "$ti_state" = success ] || problems+=("the merge task of the run is $ti_state")
  [ "$ti_tries" -gt 1 ] ||
    problems+=("the merge task of the run had $ti_tries attempt, no retry happened: the kill did not hit it")
else
  problems+=("could not read the merge task instance of $run through the REST API")
fi
if [ "${#problems[@]}" -gt 0 ]; then
  printf 'FAIL: %s\n' "${problems[@]}" >&2
  exit 1
fi
echo "silver-kill ok"
