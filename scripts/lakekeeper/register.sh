#!/usr/bin/env bash
# Register every bronze and silver table of the JDBC catalog `lake` in Lakekeeper at its current
# metadata file, then check that both catalogs point at the same file. Runs on the host, before
# the cutover, with the Spark writers stopped: a commit on either side forks the two catalogs.
# Re-running is safe: `overwrite` replaces only Lakekeeper's catalog row, never a file.
# The cutover runs it first and keeps its `same` lines as the rollback point
# (docs/runbooks/catalog-cutover.md). A table protect.sh has protected refuses the overwrite (409).
# Never undo a registration with DROP TABLE (Spark, Trino, dbt) or CALL system.unregister_table
# through any engine on the REST catalog, or with a REST DELETE: the table's files then get
# deleted, and those are the JDBC table's files too. Soft delete delays it, except Spark
# DROP ... PURGE, which deletes the files itself at once.
# lake.demo stays JDBC-only: the Iceberg demo starts with `drop ... purge`.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
shell_catalog_type=${CATALOG_TYPE:-jdbc}
set -a
# shellcheck source=/dev/null
. "$root/.env"
set +a
api=${LAKEKEEPER_API:-http://$BIND_IP:8181}
compose=(docker compose --env-file "$root/.env" -f "$root/docker/compose.yaml")

refuse() {
  echo "register.sh: $*" >&2
  exit 1
}

# get <url>: the body on stdout; on an HTTP error the body goes to stderr and get fails.
get() {
  local body
  body=$(curl -sS --fail-with-body --max-time 30 "$1") || { printf '%s\n' "$body" >&2; return 1; }
  printf '%s\n' "$body"
}

# The JDBC rows are read in a read-only transaction: this script never writes to that catalog.
jdbc_rows() {
  "${compose[@]}" exec -T -e PGOPTIONS='-c default_transaction_read_only=on' postgres-meta \
    psql -U "$META_USER" -d "$CATALOG_DB" -v ON_ERROR_STOP=1 -At -F $'\t' -c \
    "select table_namespace, table_name, metadata_location from iceberg_tables
     where catalog_name = 'lake' and table_namespace in ('bronze', 'silver')
       and coalesce(iceberg_type, 'TABLE') = 'TABLE'
     order by 1, 2"
}

# After the cutover Lakekeeper holds the live pointers and the JDBC rows are the rollback point:
# copying them over would roll every table back to its pre-cutover snapshot. Compose lets a
# CATALOG_TYPE exported in the shell win over .env, so both must say jdbc.
for catalog_type in "${CATALOG_TYPE:-}" "$shell_catalog_type"; do
  [ "$catalog_type" = jdbc ] ||
    refuse "CATALOG_TYPE is '$catalog_type' (.env or shell); registration is for before the cutover"
done

# refuse_writers <message>: writers are found by compose service label, so `compose run`
# containers (spark-silver-run-*) count too. The list is taken first: a failing docker ps must
# stop here, not read as "none". Call it as a plain command, not in $(...), or set -e is lost.
refuse_writers() {
  local containers writers
  containers=$(docker ps --format '{{.Names}} {{.Label "com.docker.compose.service"}}')
  writers=$(awk '$2 == "spark-bronze" || $2 == "spark-silver" { print $1 }' <<<"$containers")
  [ -z "$writers" ] || refuse "$1: $(paste -sd ' ' <<<"$writers")"
}

refuse_writers "Spark writers are running, stop them or let them finish"

config=$(get "$api/catalog/v1/config?warehouse=$LAKEKEEPER_WAREHOUSE")
prefix=$(python3 -c 'import json, sys; print(json.load(sys.stdin)["defaults"]["prefix"])' \
  <<<"$config")
catalog="$api/catalog/v1/$prefix"

rows=$(jdbc_rows)
[ -n "$rows" ] || refuse "no bronze or silver tables in the JDBC catalog $CATALOG_DB"
while IFS=$'\t' read -r ns name _; do
  [[ $ns =~ ^[a-z0-9_]+$ && $name =~ ^[a-z0-9_]+$ ]] || refuse "unexpected table name '$ns.$name'"
done <<<"$rows"

while read -r ns; do
  response=$(curl -sS --max-time 30 -w '\n%{http_code}' -X POST "$catalog/namespaces" \
    -H 'Content-Type: application/json' -d "{\"namespace\": [\"$ns\"]}")
  case ${response##*$'\n'} in
    200) echo "namespace $ns created" ;;
    409) ;;
    *)
      printf '%s\n' "${response%$'\n'*}" >&2
      refuse "creating namespace $ns failed"
      ;;
  esac
done < <(cut -f1 <<<"$rows" | sort -u)

while IFS=$'\t' read -r ns name location; do
  if ! response=$(python3 -c 'import json, sys
print(json.dumps({"name": sys.argv[1], "metadata-location": sys.argv[2], "overwrite": True}))' \
    "$name" "$location" | curl -sS --fail-with-body --max-time 30 -X POST \
    "$catalog/namespaces/$ns/register" -H 'Content-Type: application/json' --data @-); then
    printf '%s\n' "$response" >&2
    refuse "registering $ns.$name failed"
  fi
  echo "registered $ns.$name"
done <<<"$rows"

# A second read: a writer that committed meanwhile moves its JDBC pointer and shows up here.
after=$(jdbc_rows)
[ "$(cut -f1,2 <<<"$after")" = "$(cut -f1,2 <<<"$rows")" ] ||
  refuse "the set of JDBC tables changed during registration; run it again"
mismatches=0
while IFS=$'\t' read -r ns name location; do
  registered="cannot load the table"
  if table=$(get "$catalog/namespaces/$ns/tables/$name?snapshots=refs"); then
    registered=$(python3 -c 'import json, sys; print(json.load(sys.stdin)["metadata-location"])' \
      <<<"$table")
  fi
  if [ "$registered" = "$location" ]; then
    echo "same $ns.$name $location"
  else
    printf 'MISMATCH %s.%s\n  jdbc        %s\n  lakekeeper  %s\n' \
      "$ns" "$name" "$location" "$registered" >&2
    mismatches=$((mismatches + 1))
  fi
done <<<"$after"

# A writer started during the run commits only after its JVM is up (15-30 s), so the second
# JDBC read misses it, and its commit after the cutover would land in JDBC alone.
refuse_writers "Spark writers started during registration; stop them and run it again"
[ "$mismatches" -eq 0 ] || refuse "$mismatches of $(wc -l <<<"$after") tables differ"
echo "all $(wc -l <<<"$after") tables point at the same metadata file in both catalogs"
