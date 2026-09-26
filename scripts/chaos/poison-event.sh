#!/usr/bin/env bash
# Chaos 7, data half: a record that is not a Debezium envelope lands in oltp.shop.orders.
# Bronze keeps it as raw text, silver routes it to silver.quarantine and carries on.
. "$(dirname "$0")/lib.sh"

marker="poison-$(date +%s)"
# --sync: a failed send exits non-zero instead of being logged and forgotten.
echo "not json at all {$marker" | kafka kafka-console-producer.sh --sync --topic oltp.shop.orders
echo "produced one garbage record ($marker)"

ingested() {
  [ "$(trino_value "select count(*) from bronze.cdc_events where raw like '%$marker%'")" -ge 1 ]
}
wait_until 120 "bronze to ingest it" ingested
run_silver

trino "select reason, topic, kafka_partition, kafka_offset, payload
       from silver.quarantine where payload like '%$marker%'"
quarantined() {
  trino_value "select count(*) from silver.quarantine
               where reason = 'unparsed_envelope' and payload like '%$marker%'"
}
[ "$(quarantined)" = 1 ] || { echo "FAIL: expected one quarantine row for $marker" >&2; exit 1; }
run_silver
[ "$(quarantined)" = 1 ] || { echo "FAIL: a rerun of silver quarantined it again" >&2; exit 1; }
echo "ok: bronze kept the record, silver quarantined it once and carried on"
