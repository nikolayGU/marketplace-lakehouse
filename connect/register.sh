#!/usr/bin/env bash
# Create the CDC topics, then register (or update) the Debezium connector.
# Topics are explicit because the broker runs with auto-creation off.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
set -a
# shellcheck source=/dev/null
. "$root/.env"
set +a

connect_url="${CONNECT_URL:-http://127.0.0.1:8083}"
compose=(docker compose --env-file "$root/.env" -f "$root/docker/compose.yaml")
retention_ms=$((KAFKA_RETENTION_HOURS * 3600000))

tables=$(python3 -c '
import json, sys
config = json.load(open(sys.argv[1]))["config"]
prefix = config["topic.prefix"]
names = [t.strip() for t in config["table.include.list"].split(",")]
print(" ".join(prefix + "." + n for n in names))
' "$root/connect/shop-connector.json")

# Debezium publishes heartbeats to <heartbeat.topics.prefix>.<topic.prefix>; the prefix defaults
# to __debezium-heartbeat. It also publishes every row of the signaling table, snapshot
# watermarks included, like any captured table. Without these topics the producer blocks and the
# whole change stream stalls, because the broker will not auto-create them.
signal_topic=$(python3 -c '
import json, sys
config = json.load(open(sys.argv[1]))["config"]
print(config["topic.prefix"] + "." + config["signal.data.collection"])
' "$root/connect/shop-connector.json")
topics="$tables __debezium-heartbeat.oltp $signal_topic"

for topic in $topics; do
  "${compose[@]}" exec -T kafka /opt/kafka/bin/kafka-topics.sh \
    --bootstrap-server localhost:9092 --create --if-not-exists \
    --topic "$topic" --partitions "$KAFKA_PARTITIONS" --replication-factor 1 \
    --config "retention.ms=$retention_ms" >/dev/null
  echo "topic $topic"
done

config=$(envsubst '${DEBEZIUM_USER} ${DEBEZIUM_PASSWORD} ${OLTP_DB}' \
  < "$root/connect/shop-connector.json" \
  | python3 -c 'import json, sys; print(json.dumps(json.load(sys.stdin)["config"]))')

# PUT upserts, so re-running this script is how you apply a config change.
# The config goes over stdin to keep the password out of the process list.
printf '%s' "$config" | curl -sf -X PUT -H 'Content-Type: application/json' --data @- \
  "$connect_url/connectors/shop-connector/config" >/dev/null
echo "connector shop-connector submitted"

for _ in $(seq 60); do
  state=$(curl -sf "$connect_url/connectors/shop-connector/status" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["connector"]["state"], *(t["state"] for t in d["tasks"]))' 2>/dev/null || true)
  case "$state" in
    "RUNNING RUNNING") echo "connector and task RUNNING"; exit 0 ;;
    *FAILED*) echo "connector reported: $state" >&2; exit 1 ;;
  esac
  sleep 2
done
echo "connector did not reach RUNNING in 120s; check 'make connector-status'" >&2
exit 1
