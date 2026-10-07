#!/usr/bin/env bash
# Chaos 2: restart Kafka Connect during a replay. MODE=restart (default, SIGTERM): Connect commits
# offsets and the connector flushes the slot, so about zero repeats. MODE=kill: no final commit,
# so everything since the last offset flush (offset.flush.interval.ms, 60 s) is sent again with
# the same LSN. Silver absorbs both (OPERATIONS.md, scenarios 2a and 2b).
. "$(dirname "$0")/lib.sh"

mode=${MODE:-restart}
container=lakehouse-kafka-connect-1
case "$mode" in
  restart | kill) ;;
  *) echo "MODE must be restart or kill" >&2; exit 2 ;;
esac
t0=$(date -u +'%Y-%m-%d %H:%M:%S')

no_other_replayer
# The burst runs in a process group of its own, so an early exit or ctrl-c stops all of it.
set -m
replay_burst 180 &
burst=$!
set +m
stop_burst() { kill -TERM -- -"$burst" 2>/dev/null || true; }
trap stop_burst EXIT

sleep 90
kill -0 "$burst" 2>/dev/null ||
  { echo "the replay burst ended before the $mode; its log is above" >&2; exit 1; }
pid0=$(psql_value "select coalesce(active_pid, 0) from pg_replication_slots
                   where slot_name = 'shop_slot'")
t1=$(date -u +'%Y-%m-%d %H:%M:%S')
if [ "$mode" = restart ]; then
  docker restart "$container" >/dev/null
else
  # docker kill is a manual stop: if the script dies before docker start, Connect stays down.
  trap 'stop_burst; docker start "$container" >/dev/null' EXIT
  docker kill "$container" >/dev/null
  sleep 5
  docker start "$container" >/dev/null
  trap stop_burst EXIT
fi
echo "$mode of $container at ${t1#* }, running again at $(date -u +%T)"
wait_until 180 "connector and task RUNNING" connector_running
wait_until 180 "shop_slot streaming to a new walsender" slot_reattached "$pid0"
wait "$burst"
trap - EXIT
wait_until 300 "bronze to catch up with Kafka" bronze_caught_up

# kafka_ts is when Connect produced the record. The minute before the stop is one offset flush
# interval: without traffic there, "0 repeats" would prove nothing.
counts=$(trino_value "
  select count_if(kafka_ts >= timestamp '$t1 UTC' - interval '60' second
                  and kafka_ts < timestamp '$t1 UTC'),
         count_if(kafka_ts >= timestamp '$t1 UTC')
  from bronze.cdc_events where ingest_ts >= timestamp '$t0 UTC'")
read -r before after <<<"$counts"
echo "CDC events produced in the 60 s before the $mode: $before, after it: $after"
if ! [ "$before" -gt 0 ] || ! [ "$after" -gt 0 ]; then
  echo "inconclusive: no CDC traffic on one side of the $mode (schedule drained?); run again" >&2
  exit 1
fi

lsn_duplicates_since "$t0"
if [ "$mode" = kill ]; then
  repeated=$(trino_value "select count(*) from (
                            select 1 from bronze.cdc_events
                            where ingest_ts >= timestamp '$t0' and lsn is not null
                            group by source_table, key, lsn having count(*) > 1)")
  if ! [ "$repeated" -gt 0 ]; then
    echo "inconclusive: the kill repeated no event, it came right after an offset flush;" \
      "run again" >&2
    exit 1
  fi
fi

run_silver
reconcile
echo "expected: MODE=restart no rows above; MODE=kill repeated events; reconcile ok (live row" \
  "counts) either way"
