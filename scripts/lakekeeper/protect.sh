#!/usr/bin/env bash
# Set protected=true on every bronze and silver table in Lakekeeper. Lakekeeper then answers a drop
# of such a table with 409 before anything is deleted: Spark DROP with or without PURGE, Trino DROP
# and unregister_table, a REST DELETE, a register overwrite. Only force=true gets past it. Commits
# are not affected. Runs on the host after the cutover checks (docs/runbooks/catalog-cutover.md).
# Safe to re-run, also when a new bronze or silver table appears: it only ever sends
# protected=true, reads the flag back and changes nothing else. Removing protection is on the
# blast-radius list and is not done here.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
set -a
# shellcheck source=/dev/null
. "$root/.env"
set +a
api=${LAKEKEEPER_API:-http://$BIND_IP:8181}
uuid_re='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'

refuse() {
  echo "protect.sh: $*" >&2
  exit 1
}

# get <url>: the body on stdout; on an HTTP error the body goes to stderr and get fails.
get() {
  local body
  body=$(curl -sS --fail-with-body --max-time 30 "$1") || { printf '%s\n' "$body" >&2; return 1; }
  printf '%s\n' "$body"
}

# protect <url>: POST protected=true; on an HTTP error the body goes to stderr and it fails.
protect() {
  local body
  body=$(curl -sS --fail-with-body --max-time 30 -X POST "$1" \
    -H 'Content-Type: application/json' -d '{"protected": true}') ||
    { printf '%s\n' "$body" >&2; return 1; }
}

# field <expression over d> < json: one value of a JSON document.
field() {
  python3 -c "import json, sys; d = json.load(sys.stdin); print($1)"
}

config=$(get "$api/catalog/v1/config?warehouse=$LAKEKEEPER_WAREHOUSE")
# The REST prefix is the warehouse id, which the management API takes.
warehouse_id=$(field 'd["defaults"]["prefix"]' <<<"$config")
[[ $warehouse_id =~ $uuid_re ]] || refuse "unexpected warehouse id '$warehouse_id'"
catalog="$api/catalog/v1/$warehouse_id"

# All tables first, so a failing listing stops the script before the first change.
tables=()
for ns in bronze silver; do
  token="" found=0
  while :; do
    page=$(get "$catalog/namespaces/$ns/tables${token:+?pageToken=$token}")
    parsed=$(python3 -c 'import json, sys, urllib.parse
d = json.load(sys.stdin)
print(urllib.parse.quote(d.get("next-page-token") or "", safe=""))
for ident in d["identifiers"]:
    print(ident["name"])' <<<"$page")
    {
      read -r token
      while read -r name; do
        [[ $name =~ ^[a-z0-9_]+$ ]] || refuse "unexpected table name '$ns.$name'"
        tables+=("$ns.$name")
        found=$((found + 1))
      done
    } <<<"$parsed"
    [ -n "$token" ] || break
  done
  [ "$found" -gt 0 ] || refuse "no tables in namespace $ns of warehouse $LAKEKEEPER_WAREHOUSE"
done

for table in "${tables[@]}"; do
  ns=${table%%.*}
  name=${table#*.}
  metadata=$(get "$catalog/namespaces/$ns/tables/$name?snapshots=refs")
  # Lakekeeper keys a table by the table-uuid of its metadata, registered tables included.
  table_id=$(field 'd["metadata"]["table-uuid"]' <<<"$metadata")
  [[ $table_id =~ $uuid_re ]] || refuse "unexpected table-uuid '$table_id' of $table"
  url="$api/management/v1/warehouse/$warehouse_id/table/$table_id/protection"

  status=$(get "$url")
  protected=$(field 'd["protected"]' <<<"$status")
  if [ "$protected" = True ]; then
    action="already protected"
  else
    protect "$url" || refuse "setting protection on $table failed"
    action="protected"
  fi
  status=$(get "$url")
  protected=$(field 'd["protected"]' <<<"$status")
  [ "$protected" = True ] || refuse "$table ($table_id) reads back protected=$protected"
  echo "$action $table $table_id"
done
echo "all ${#tables[@]} bronze and silver tables are protected"
