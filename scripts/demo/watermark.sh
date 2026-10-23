#!/usr/bin/env bash
# Watermark demo (W5-T01a, ADR-024): the same job code as the live service, on a lab topic, one
# availableNow run per batch on one checkpoint, into lake.demo.orders_per_minute.
#
#   run 1  orders at 10:00:10, 10:04:30, 10:10:20            watermark moves to 10:05:20
#   run 2  an order at 10:07:40                              inside the watermark: a new window
#   run 3  an order at 10:04:50 and order 3 again            behind it: dropped; a resend: once
#
# Spark drops a late row against the watermark of the previous batch, so the late order has to
# come one batch after the batch that moved the watermark (tests/unit/test_orders_per_minute.py).
# The orders are made up, dated one day per run from 2000-01-01, and live only in the lab topic;
# the topic that bronze reads and `reconcile` compares is not touched.
. "$(dirname "$0")/../chaos/lib.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }

# `live`: the same two cases on the running service (W5-T01b). Two real inserts are sent again to
# oltp.shop.orders: the oldest one far behind the watermark (it must be dropped, once) and the
# newest one (inside the watermark, already counted, so nothing changes). Both also reach bronze
# and silver, where the LSN guard absorbs them (as in chaos 4); lsn_repeats_last_hour grows by 2.
# Only orders bronze took in during the last 12 hours: Kafka keeps 24 hours and bronze keeps more.
if [ "${1:-demo}" = live ]; then
  no_other_replayer
  connector_running || fail "the connector is not RUNNING"
  service_healthy spark-orders-per-minute || fail "spark-orders-per-minute is not healthy (make up PROFILE=stateful)"
  bronze_caught_up || fail "bronze has not caught up with Kafka"

  metric() {
    "${COMPOSE[@]}" --profile stateful exec -T spark-orders-per-minute curl -s localhost:4041/metrics |
      awk -v m="$1" '$1 ~ "^" m "{query=\"orders_per_minute\"}$" {print int($2); found=1} END {if (!found) print 0}'
  }
  total() { trino_value "select coalesce(sum(orders), 0) from silver.orders_per_minute"; }
  # wait_batch <input rows before>: the service has read at least one more row.
  wait_batch() { [ "$(metric spark_streaming_input_rows_total)" -gt "$1" ]; }

  newest_window=$(trino_value "select cast(max(window_start) as varchar) from silver.orders_per_minute")
  [ -n "$newest_window" ] && [ "$newest_window" != NULL ] ||
    fail "silver.orders_per_minute is empty: let the service read a burst first"
  echo "newest window in silver.orders_per_minute: $newest_window"
  purchase="from_unixtime(cast(json_extract_scalar(after, '\$.order_purchase_timestamp') as bigint) / 1000)"
  pick() { # pick <order by>: partition and offset of one insert, from bronze
    trino_value "select kafka_partition, kafka_offset from bronze.cdc_events
                 where source_table = 'orders' and op = 'c' and $2
                   and ingest_ts > current_timestamp - interval '12' hour
                 order by $purchase $1 limit 1"
  }

  resend() { # resend <label> <partition> <offset>: publish the record of that offset again
    local record
    record=$(kafka kafka-console-consumer.sh --topic oltp.shop.orders --partition "$2" \
      --offset "$3" --max-messages 1 --timeout-ms 20000 \
      --formatter-property print.key=true --formatter-property key.separator=$'\t')
    [ -n "$record" ] || fail "could not read offset $3 of partition $2"
    local rows_before dropped_before sum_before
    rows_before=$(metric spark_streaming_input_rows_total)
    dropped_before=$(metric spark_streaming_late_rows_dropped_total)
    sum_before=$(total)
    printf '%s\n' "$record" | kafka kafka-console-producer.sh --sync --topic oltp.shop.orders \
      --reader-property parse.key=true --reader-property key.separator=$'\t'
    wait_until 120 "the service to read the re-sent $1 order" wait_batch "$rows_before"
    # The metric moves when the batch is read; the MERGE and the counter come right after it.
    sleep 25
    echo "$1: orders $sum_before -> $(total), dropped $dropped_before -> $(metric spark_streaming_late_rows_dropped_total)"
    [ "$(total)" = "$sum_before" ] || fail "the $1 order changed the sum of orders"
    DROPPED_DELTA=$(($(metric spark_streaming_late_rows_dropped_total) - dropped_before))
  }

  read -r p o <<<"$(pick asc "$purchase <= timestamp '$newest_window' - interval '1' hour")"
  [ -n "$o" ] || fail "no order older than an hour before the newest window in bronze"
  resend "late" "$p" "$o"
  [ "$DROPPED_DELTA" = 1 ] || fail "the late order was expected to be dropped once, delta $DROPPED_DELTA"
  read -r p o <<<"$(pick desc "true")"
  resend "newest" "$p" "$o"
  [ "$DROPPED_DELTA" = 0 ] || fail "the newest order was dropped by the watermark, delta $DROPPED_DELTA"
  echo "ok: the late order was dropped once, the newest was counted once, the sums did not move"
  exit 0
fi

run_id=$(date -u +%Y%m%d%H%M%S)
topic="lab.orders.$run_id"
# One day per run: a rerun cannot pass on rows an earlier run left in the table.
day=$(python3 -c "import datetime,sys; print(datetime.date(2000,1,1)+datetime.timedelta(days=int(sys.argv[1])%3000))" "$((10#${run_id:8:6} + 7))")

# publish <id:HH:MM:SS>...: one Debezium-shaped insert per argument, with the purchase time on $day.
publish() {
  python3 - "$day" "$@" <<'PY' | kafka kafka-console-producer.sh --sync --topic "$topic"
import calendar, json, sys
day, *orders = sys.argv[1:]
y, m, d = map(int, day.split("-"))
for spec in orders:
    order_id, hh, mm, ss = spec.split(":")
    ms = calendar.timegm((y, m, d, int(hh), int(mm), int(ss))) * 1000
    print(json.dumps({
        "op": "c", "ts_ms": 1790104945151, "before": None,
        "after": {"order_id": order_id, "order_purchase_timestamp": ms},
        "source": {"lsn": 1, "sequence": None, "ts_ms": 1790104944721, "table": "orders"},
    }))
PY
}

# run_job: one availableNow pass over what the topic holds new since the last pass.
run_job() {
  "${COMPOSE[@]}" --profile core run --rm --no-deps \
    -e OPM_SOURCE_TOPIC="$topic" -e OPM_TARGET=lake.demo.orders_per_minute \
    -e OPM_CHECKPOINT="s3a://${S3_BUCKET}/checkpoints/orders_per_minute_demo/$run_id" \
    -e OPM_TRIGGER=available_now spark-silver orders_per_minute 2>&1 | grep -E '^progress batch=' |
    tee -a "$progress"
}

progress=$(mktemp -t watermark_demo.XXXXXX.log)
kafka kafka-topics.sh --create --topic "$topic" --partitions 1 --replication-factor 1 \
  --config retention.ms=3600000 >/dev/null
echo "lab topic $topic, orders dated $day"

echo "-- run 1: three orders"
publish "demo-$run_id-1:10:00:10" "demo-$run_id-2:10:04:30" "demo-$run_id-3:10:10:20"
run_job
echo "-- run 2: an order inside the watermark"
publish "demo-$run_id-4:10:07:40"
run_job
echo "-- run 3: an order behind the watermark, and order 3 sent again"
publish "demo-$run_id-5:10:04:50" "demo-$run_id-3:10:10:20"
run_job

query="select date_format(window_start, '%H:%i'), orders from demo.orders_per_minute
       where window_start >= timestamp '$day 00:00:00'
         and window_start < timestamp '$day 00:00:00' + interval '1' day order by 1"
trino "$query"
got=$(trino_value "$query" | tr '\t\n' ' ')
want='10:00 1 10:04 1 10:07 1 10:10 1 '
[ "$got" = "$want" ] || fail "windows are [$got], expected [$want]"
grep -qE 'dropped=[1-9]' "$progress" || fail "no batch reported a row dropped by the watermark"
echo "dropped by the watermark: $(grep -oE 'batch=[0-9]+ .* dropped=[1-9][0-9]*' "$progress" | tail -1)"
rm -f "$progress"
echo "ok: inside watermark updated, outside dropped, duplicate counted once"
