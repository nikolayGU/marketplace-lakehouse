#!/usr/bin/env bash
# Ask the running connector for an incremental snapshot (ADR-019).
# Usage: snapshot.sh [shop.table ...]; with no arguments, every table in table.include.list.
# Non-destructive: the slot and offsets stay put, rows arrive as op=r alongside live changes.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
set -a
# shellcheck source=/dev/null
. "$root/.env"
set +a

compose=(docker compose --env-file "$root/.env" -f "$root/docker/compose.yaml")

signal=$(python3 -c '
import json, sys, time
config = json.load(open(sys.argv[1]))["config"]
tables = sys.argv[2:] or [t.strip() for t in config["table.include.list"].split(",")]
unknown = set(tables) - {t.strip() for t in config["table.include.list"].split(",")}
if unknown:
    sys.exit(f"not captured by the connector: {sorted(unknown)}")
data = json.dumps({"data-collections": tables, "type": "incremental"})
print(config["signal.data.collection"], f"snapshot-{int(time.time())}", data, sep="\t")
' "$root/connect/shop-connector.json" "$@")

IFS=$'\t' read -r table id data <<<"$signal"

"${compose[@]}" exec -T postgres-oltp psql -v ON_ERROR_STOP=1 -q \
  -U "$OLTP_USER" -d "$OLTP_DB" -v table="$table" -v id="$id" -v data="$data" <<'EOSQL'
insert into :table (id, type, data) values (:'id', 'execute-snapshot', :'data');
EOSQL
echo "signal $id sent: $data"
echo "progress: docker logs lakehouse-kafka-connect-1 2>&1 | grep -i 'incremental snapshot'"
