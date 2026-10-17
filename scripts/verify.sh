#!/usr/bin/env bash
# make verify: data went through the whole stack. Bronze holds every Kafka record exactly once,
# silver equals Postgres, all seven source tables reached bronze. Ends with `verify ok` or the
# reason and a non-zero exit code. It runs one silver merge, so it refuses while Airflow may run
# another (two writers on one checkpoint) and while a replayer plays (reconcile would compare a
# moving source).
. "$(dirname "$0")/chaos/lib.sh"

fail() {
  echo "verify failed: $*" >&2
  exit 1
}

if [ -n "$("${COMPOSE[@]}" --profile '*' ps -q airflow-scheduler)" ]; then
  echo "airflow-scheduler is running and may merge silver at the same time: pause silver_upsert" \
    "and stop the scheduler first (OPERATIONS.md, Airflow)" >&2
  exit 2
fi
no_other_replayer
wait="${VERIFY_WAIT:-900}"
wait_until "$wait" "bronze to catch up with Kafka" bronze_caught_up ||
  fail "bronze did not catch up with Kafka in $wait s"
run_silver || fail "silver_upsert failed"
bronze_offsets_ok || fail "bronze holds a Kafka offset twice or misses one"
reconcile || fail "silver differs from Postgres, or a reconcile query failed (table above)"
tables=$(trino_value "select count(distinct source_table) from bronze.cdc_events
                      where source_table in ('customers', 'sellers', 'products', 'orders',
                                             'order_items', 'payments', 'reviews')") ||
  fail "counting the source tables in bronze failed"
[ "$tables" = 7 ] || fail "bronze holds events of $tables of the 7 source tables"
echo "verify ok"
