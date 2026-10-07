#!/usr/bin/env bash
# Chaos 4: an older change of an order arrives after a newer one, the way Debezium re-sends after
# a kill (chaos 2b; a graceful restart re-sends nothing). The script re-publishes an earlier
# envelope of an order silver has already moved past and checks that silver keeps the newer state
# (the _last_lsn guard, ADR-021).
. "$(dirname "$0")/lib.sh"

no_other_replayer
# A stack that cannot carry the burst fails here, before it costs a virtual day.
if ! connector_running; then
  echo "shop-connector or its task is not RUNNING; see docs/runbooks/connector-failed.md" >&2
  exit 1
fi
if ! healthy lakehouse-spark-bronze-1; then
  echo "lakehouse-spark-bronze-1 is not healthy; see docs/runbooks/spark-stalled.md" >&2
  exit 1
fi

t0=$(date -u +'%Y-%m-%d %H:%M:%S')
echo "window: ingest_ts >= timestamp '$t0' (UTC)"
replay_burst 120
wait_until 300 "bronze to catch up with Kafka" bronze_caught_up
echo "bronze caught up at $(date -u +%T)"
run_silver

# The oldest change, insert or update, of an order with a newer one. Comparing LSNs, not counting
# rows, keeps two copies of one change (a Connect re-send) from passing for two changes.
pick=$(trino_value "
  with ev as (
    select json_extract_scalar(after, '\$.order_id') as order_id,
           kafka_partition, kafka_offset, lsn
    from bronze.cdc_events
    where source_table = 'orders' and op in ('c', 'u') and ingest_ts >= timestamp '$t0'),
  ranked as (
    select *, row_number() over (partition by order_id order by lsn) as n,
              max(lsn) over (partition by order_id) as newest
    from ev)
  select order_id, kafka_partition, kafka_offset, lsn, newest from ranked
  where n = 1 and lsn < newest limit 1")
read -r order_id partition offset stale_lsn newest <<<"$pick"
if [ -z "$order_id" ]; then
  echo "inconclusive: no order changed twice in this burst; run again" >&2
  exit 1
fi
state="select order_status, _last_lsn from silver.orders where order_id = '$order_id'"
before=$(trino_value "$state")
# Silver must be past the stale LSN. At an equal LSN the row reads the same afterwards and proves
# nothing; with no row, a null or a lower LSN, MERGE takes the re-sent change and the run fails
# for the wrong reason.
silver_lsn=$(cut -s -f2 <<<"$before")
if ! [[ $silver_lsn =~ ^[0-9]+$ ]] || ((silver_lsn <= stale_lsn)); then
  echo "FAIL: silver has [$before] for order $order_id, not past lsn $stale_lsn (newest in" \
    "bronze $newest): the first silver run did not apply the newer change" >&2
  exit 1
fi
echo "order $order_id: silver has [$before]; re-sending its change at lsn $stale_lsn" \
  "(partition $partition, offset $offset; newest in bronze $newest)"

record=$(kafka kafka-console-consumer.sh --topic oltp.shop.orders --partition "$partition" \
  --offset "$offset" --max-messages 1 --timeout-ms 20000 \
  --formatter-property print.key=true --formatter-property key.separator=$'\t')
[ -n "$record" ] || { echo "could not read offset $offset of partition $partition" >&2; exit 1; }
stale_copies() {
  trino_value "select count(*) from bronze.cdc_events
               where lsn = $stale_lsn and source_table = 'orders'"
}
# Bronze is caught up and the burst is over: only the re-sent record can move this count.
copies=$(stale_copies)
# --sync: a failed send exits non-zero instead of being logged and forgotten.
printf '%s\n' "$record" | kafka kafka-console-producer.sh --sync --topic oltp.shop.orders \
  --reader-property parse.key=true --reader-property key.separator=$'\t'
echo "re-sent at $(date -u +%T)"
resent() { [ "$(stale_copies)" -gt "$copies" ]; }
wait_until 120 "bronze to take in the re-sent record" resent

# Positive control: a silver run that never read the re-sent record would leave the row as it was
# too, so this run must report orders events merged. Kept in a file on failure, like run_silver.
log=$(mktemp -t silver_upsert.XXXXXX.log)
if ! make -C "$ROOT" --no-print-directory silver >"$log" 2>&1; then
  tail -40 "$log" >&2
  echo "silver_upsert failed, full log: $log" >&2
  exit 1
fi
merged=$(grep -E 'batch [0-9]+: [0-9]+ events merged into lake\.silver\.orders in' "$log") || true
if [ -z "$merged" ]; then
  echo "FAIL: the second silver run merged no orders event, the guard was never exercised;" \
    "full log: $log" >&2
  exit 1
fi
rm -f "$log"
printf '%s\n' "$merged"

after=$(trino_value "$state")
trino "select kafka_partition, kafka_offset, lsn,
              json_extract_scalar(after, '\$.order_status') as status, ingest_ts
       from bronze.cdc_events where lsn = $stale_lsn and source_table = 'orders'"
echo "silver before [$before], after [$after]"
if [ "$before" != "$after" ]; then
  echo "FAIL: the late event changed the order" >&2
  exit 1
fi
echo "ok: the late event did not roll the order back"
