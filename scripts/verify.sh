#!/usr/bin/env bash
# make verify: data went through the whole stack. Bronze holds every Kafka record exactly once,
# silver matches Postgres on row count, key set, decimal sums and a fingerprint of every column
# (`make reconcile`), all seven source tables reached bronze. Ends with
# `verify ok` or the reason and a non-zero exit code. It runs one silver merge, so it refuses
# while Airflow may run another (two writers on one checkpoint) and while a replayer plays
# (reconcile would compare a moving source). `--no-merge` (make verify-fast) skips the merge and
# writes nothing to the lake.
# On success it stamps the working tree (.verify-stamp) for the agent hooks in .claude/hooks.
. "$(dirname "$0")/chaos/lib.sh"

mode=full
case "${1:-}" in
  "") ;;
  --no-merge) mode=fast ;;
  *) echo "usage: verify.sh [--no-merge]" >&2; exit 2 ;;
esac

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
python3 "$ROOT/scripts/agent_state.py" stamp "$mode" "$ROOT"
echo "verify ok"
