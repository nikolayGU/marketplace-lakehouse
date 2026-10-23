#!/usr/bin/env bash
# Chaos 6: the connector is stopped for up to HOLD seconds (default 1800) while the source is
# written. The slot, with no consumer, holds WAL back: the alert has to see it before the disk
# does (OPERATIONS.md, scenario 6). STOP, not PAUSE: a paused task keeps the walsender, the slot
# stays active and SlotWalRetainedHigh (inactive slot over 64 MiB) cannot fire (W4-D11).
. "$(dirname "$0")/lib.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }
hold=${HOLD:-1800}
connect=http://127.0.0.1:8083/connectors/shop-connector

no_other_replayer
connector_running || fail "the connector is not RUNNING before the stop"
bronze_caught_up || fail "bronze has not caught up with Kafka before the stop"
wait_until 1200 "SlotWalRetainedHigh to be quiet" alert_quiet SlotWalRetainedHigh

# STOPPED is kept in connect-configs and survives a Connect restart: a script that dies without
# this leaves CDC off for good.
resume() { curl -sf -X PUT "$connect/resume" >/dev/null || echo "COULD NOT RESUME: curl -X PUT $connect/resume" >&2; }
trap resume EXIT

pid0=$(psql_value "select coalesce(active_pid, 0) from pg_replication_slots
                   where slot_name = 'shop_slot'")
base=$(slot_retained_bytes)
start=$SECONDS
curl -sf -X PUT "$connect/stop" >/dev/null || fail "could not stop the connector"
echo "stopped the connector at $(date -u +%T), slot held $base bytes"

inactive() { [ "$(psql_value "select active from pg_replication_slots where slot_name = 'shop_slot'")" = f ]; }
wait_until 60 "the slot to turn inactive" inactive ||
  fail "the slot stays active after a STOP: W4-D11 needs a rethink"
echo "slot inactive $((SECONDS - start)) s after the stop"
alert_firing ConnectorNotRunning 180

# Traffic while the consumer is gone, then WAL padding up to the threshold: the schedule yields
# ~1.1 MB of WAL per virtual hour (13.6 MB for 60 s, W4-T02), so reaching 64 MiB by replay alone
# would spend days of the budget. Not pg_logical_emit_message: Debezium decodes those and publishes
# them to oltp.message, a topic that does not exist; the first run of this scenario stopped CDC on
# its 4 MB records. A transaction plus pg_switch_wal adds one 16 MB segment per round and produces
# nothing Debezium forwards.
replay_burst 30
while [ "$(slot_retained_bytes)" -lt $((72 * 1024 * 1024)) ]; do
  psql_value "select txid_current()" >/dev/null
  psql_value "select pg_switch_wal()" >/dev/null
done
echo "slot holds $(slot_retained_bytes) bytes"
alert_firing SlotWalRetainedHigh 900

while ((SECONDS - start < hold)); do sleep 15; done
curl -sf -X PUT "$connect/resume" >/dev/null || fail "could not resume the connector"
trap - EXIT
echo "resumed at $(date -u +%T), $((SECONDS - start)) s after the stop"
wait_until 180 "the connector and task RUNNING" connector_running
wait_until 180 "shop_slot streaming to a new walsender" slot_reattached "$pid0"
wait_until 900 "bronze to catch up with Kafka" bronze_caught_up
echo "bronze caught up $((SECONDS - start)) s after the stop"
bronze_offsets_ok || fail "a Kafka offset is in bronze twice or missing"
merge_silver
reconcile
# The connector only confirms what it has read once a real change arrives, so a small burst after
# the resume is what shows the slot drained. restart_lsn (what the alert reads) lags behind the
# confirmed position until Postgres logs the next running-transactions record, so it is printed,
# not asserted.
replay_burst 15
wait_until 300 "bronze to catch up with Kafka" bronze_caught_up
sleep 30
unconfirmed=$(psql_value "select pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)::bigint
                          from pg_replication_slots where slot_name = 'shop_slot'")
echo "unconfirmed WAL after the catch-up: $unconfirmed bytes, retained by restart_lsn: $(slot_retained_bytes)"
[ "$unconfirmed" -lt $((1024 * 1024)) ] || fail "the connector has not confirmed the WAL it read"
merge_silver
reconcile
alerts_in_window $((SECONDS - start + 60))
echo "ok: nothing lost while the connector was stopped, the slot drained, silver equals Postgres"
