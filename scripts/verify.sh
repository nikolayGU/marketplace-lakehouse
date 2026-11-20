#!/usr/bin/env bash
# make verify: data went through the whole stack. Bronze has caught up with Kafka's end offsets
# and holds no Kafka offset twice and no gap between the lowest and the highest offset of each
# partition (the start of a partition, which retention may have removed before bronze read it, is
# not checked), silver matches Postgres on row count, key set, decimal sums and a fingerprint of
# every column (`make reconcile`), all seven source tables reached bronze. Ends with
# `verify ok` or the reason and a non-zero exit code. It runs one silver merge, so it refuses
# while Airflow may run another (two writers on one checkpoint) and while a replayer plays
# (reconcile would compare a moving source), and when Trino does not answer `select 1` or its
# catalog lake does not answer `show schemas` (Lakekeeper down) or MinIO does not answer a health
# check run in the trino container against the endpoint of its catalog (MinIO down; not a table
# query: Trino caches metadata). The probes run after the other two checks, one after the other,
# each ends within TRINO_PROBE_WAIT (default 20) + 2 s at most, so a refusal comes within three
# times that.
# `--no-merge` (make verify-fast) skips the merge and writes nothing to the lake.
# On success it stamps for the agent hooks in .claude/hooks the working tree as it was when verify
# started (a file edited during the run is not covered). A stamp that fails (no git, no .venv) is
# reported on stderr and does not fail verify: the data checks passed, and the commit gate stays
# closed without the stamp.
# shellcheck source-path=SCRIPTDIR source=chaos/lib.sh
. "$(dirname "$0")/chaos/lib.sh"

# bash runs a trap once the foreground command ends: a Ctrl+C that only the script gets (the Trino
# probe has a process group of its own) ends it right after that command, with this message and
# exit code 130. TERM has no trap, so a kill still ends the script at once, even during a merge.
trap 'echo "verify interrupted" >&2; rm -f "${probe_out:-}"; exit 130' INT

mode=full
case "${1:-}" in
  "") ;;
  --no-merge) mode=fast ;;
  *) echo "usage: verify.sh [--no-merge]" >&2; exit 2 ;;
esac
python="$ROOT/.venv/bin/python"
tree=$("$python" "$ROOT/scripts/agent_state.py" tree "$ROOT" 2>/dev/null) || tree=""

fail() {
  echo "verify failed: $*" >&2
  exit 1
}

if [ "$mode" = full ]; then
  scheduler=$("${COMPOSE[@]}" --profile '*' ps -q airflow-scheduler) || {
    echo "docker compose ps failed: cannot tell whether airflow-scheduler runs" >&2
    exit 2
  }
  if [ -n "$scheduler" ]; then
    echo "airflow-scheduler is running and may merge silver at the same time: pause" \
      "silver_upsert and stop the scheduler first (OPERATIONS.md, Airflow)" >&2
    exit 2
  fi
fi
no_other_replayer
# Every check below needs Trino, its catalog lake and the object store: without these probes any
# one down shows as bronze not catching up.
# trino_up runs in this shell, not in $(...): the INT trap then fires after the probe that was
# running, before the next one starts. It leaves its reason in trino_up_err.
trino_up || {
  echo "verify failed: $trino_up_err" >&2
  exit 2
}
wait="${VERIFY_WAIT:-900}"
wait_until "$wait" "bronze to catch up with Kafka" bronze_caught_up ||
  fail "bronze did not catch up with Kafka in $wait s"
if [ "$mode" = full ]; then
  run_silver || fail "silver_upsert failed"
fi
bronze_offsets_ok || fail "bronze holds a Kafka offset twice or misses one"
reconcile || fail "silver differs from Postgres, or a reconcile query failed (table above)"
tables=$(trino_value "select count(distinct source_table) from bronze.cdc_events
                      where source_table in ('customers', 'sellers', 'products', 'orders',
                                             'order_items', 'payments', 'reviews')") ||
  fail "counting the source tables in bronze failed"
[ "$tables" = 7 ] || fail "bronze holds events of $tables of the 7 source tables"
if [ -z "$tree" ]; then
  echo "verify: the working tree was not stamped (its tree id could not be read: no git" \
    "repository or no .venv); the checks above passed" >&2
elif said=$("$python" "$ROOT/scripts/agent_state.py" stamp "$mode" "$ROOT" "$tree" 2>&1); then
  # What the stamp did, e.g. that a full stamp covering this tree was kept by a fast run.
  [ -z "$said" ] || echo "verify: $said" >&2
else
  echo "verify: the working tree was not stamped (${said##*$'\n'}); the checks above passed" >&2
fi
echo "verify ok"
