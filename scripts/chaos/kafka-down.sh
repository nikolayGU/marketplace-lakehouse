#!/usr/bin/env bash
# Chaos 8: Kafka stops for KAFKA_DOWN seconds (default 360) while the source is written. Connect
# cannot produce and the slot holds the WAL; Spark cannot read. The run fails only on a data
# check; which alerts fired is recorded, not asserted (OPERATIONS.md, scenario 8).
. "$(dirname "$0")/lib.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }
down=${KAFKA_DOWN:-360}

no_other_replayer
connector_running || fail "the connector is not RUNNING before the stop"
bronze_caught_up || fail "bronze has not caught up with Kafka before the stop"
wait_until 1200 "ContainerRestarting to be quiet" alert_quiet ContainerRestarting

# The burst runs in a process group of its own, so an early exit or ctrl-c stops all of it.
set -m
replay_burst 120 &
burst=$!
set +m
stop_burst() { kill -TERM -- -"$burst" 2>/dev/null || true; }
start_kafka() { "${COMPOSE[@]}" --profile '*' start kafka >/dev/null; }
trap 'stop_burst; start_kafka' EXIT

start=$SECONDS
sleep 30
kill -0 "$burst" 2>/dev/null ||
  { echo "the replay burst ended before the stop; its log is above" >&2; exit 1; }
"${COMPOSE[@]}" --profile '*' stop kafka >/dev/null
echo "stopped kafka at $(date -u +%T) ($((SECONDS - start)) s into the burst), down for $down s"
sleep "$down"
start_kafka
up=$SECONDS
trap stop_burst EXIT
wait_until 180 "kafka to turn healthy" service_healthy kafka
echo "kafka healthy $((SECONDS - up)) s after the start"
wait_until 300 "connector and task RUNNING" connector_running
echo "connector RUNNING $((SECONDS - up)) s after the start"
wait "$burst" || true
trap - EXIT

wait_until 900 "bronze to catch up with Kafka" bronze_caught_up
echo "bronze caught up $((SECONDS - up)) s after the start"
bronze_offsets_ok || fail "a Kafka offset is in bronze twice or missing"
bronze_offsets_report
merge_silver
reconcile
echo "alerts firing since the stop:"
alerts_in_window $((SECONDS - start + 60))
echo "ok: after $down s without Kafka every offset is in bronze once, silver equals Postgres"
