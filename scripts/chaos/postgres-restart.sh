#!/usr/bin/env bash
# Chaos 5: restart PostgreSQL under a running CDC pipeline. The answer is what the system does,
# not a fix: if the Debezium task does not come back by itself the run fails and names the
# runbook (OPERATIONS.md, scenario 5; docs/runbooks/connector-failed.md).
. "$(dirname "$0")/lib.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }

no_other_replayer
connector_running || fail "the connector is not RUNNING before the restart"
bronze_caught_up || fail "bronze has not caught up with Kafka before the restart"
wait_until 1200 "ContainerRestarting to be quiet" alert_quiet ContainerRestarting

pid0=$(psql_value "select coalesce(active_pid, 0) from pg_replication_slots
                   where slot_name = 'shop_slot'")
flush0=$(psql_value "select confirmed_flush_lsn from pg_replication_slots
                     where slot_name = 'shop_slot'")
t0=$(date -u +'%Y-%m-%d %H:%M:%S')
start=$SECONDS
"${COMPOSE[@]}" restart postgres-oltp >/dev/null
echo "restarted postgres-oltp at ${t0#* }, slot was at $flush0, walsender $pid0"
wait_until 180 "postgres-oltp to turn healthy" service_healthy postgres-oltp
echo "postgres healthy after $((SECONDS - start)) s"

# The connector may still report RUNNING for a while after the restart; a new walsender on the
# slot is what proves it connected again.
if ! wait_until 300 "the connector to stream from a new walsender" slot_reattached "$pid0"; then
  echo "the Debezium task did not reconnect within 300 s: this is the system's answer," \
    "see docs/runbooks/connector-failed.md" >&2
  curl -s http://127.0.0.1:8083/connectors/shop-connector/status >&2 || true
  exit 1
fi
wait_until 60 "connector and task RUNNING" connector_running
echo "connector streaming again after $((SECONDS - start)) s"

# The burst comes after the restart: the replayer writes to Postgres from the host and would
# die with it.
replay_burst 30
first=$SECONDS
wait_until 300 "bronze to catch up with Kafka" bronze_caught_up
echo "bronze caught up $((SECONDS - first)) s after the burst"
bronze_offsets_ok || fail "a Kafka offset is in bronze twice or missing"
merge_silver
reconcile

alert_firing ContainerRestarting 180
echo "alerts firing in the last $((SECONDS - start + 60)) s:"
alerts_in_window $((SECONDS - start + 60))
echo "ok: the pipeline reconnected without a hand, every offset once, silver equals Postgres"
