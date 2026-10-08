# Catalog cutover: JDBC to Lakekeeper

Switches Spark and Trino from the JDBC catalog in `postgres-meta` to Lakekeeper (ADR-005). Run it
only after the owner's ok on this runbook. Bronze is stopped from step 1 to step 3, a few minutes;
Kafka keeps what bronze has not read for 24 h. The cutover moves no data file, checkpoint or Kafka
offset: both catalogs point at the same metadata files, and the JDBC rows stay untouched as the
rollback point until the end of week 3.

One moment matters: bronze's first commit through Lakekeeper (step 4b). Before it, the rollback
is free. After it, only Lakekeeper holds the current pointers, and going back to JDBC means DML on
`iceberg_catalog`, which only the owner runs.

## Before you start

- The tree holds the cutover config: `lakekeeper`, `lakekeeper-migrate` and `lakekeeper-bootstrap`
  in profile `core` of `docker/compose.yaml`, with `spark-bronze`, `spark-silver` and `trino`
  waiting for `lakekeeper-bootstrap`; `docker/trino/etc/catalog/lake.properties` on REST;
  `CATALOG_TYPE=rest` in `.env.example` and as the default in `streaming/spark_jobs/settings.py`.
  `make lint`, `make test` and `make test-spark` are green.
- `core` and `query` are healthy (`make status`), `lakekeeper` included, and `make
  lakekeeper-bootstrap` prints `warehouse lake exists`. No `spark-silver` container runs, and no
  replayer plays: `bash -c '. scripts/chaos/lib.sh && no_other_replayer'` prints nothing.
- Trino still serves JDBC. It reads `lake.properties` only at startup, so this line ends in `JDBC`:
  `docker logs lakehouse-trino-1 2>&1 | grep -P 'catalog\.lake\t+iceberg\.catalog\.type\s' | tail -1`.
  If it ends in `REST`, Trino restarted early and reads Lakekeeper's pointers, which stop moving
  with bronze's next JDBC commit. Nothing writes through Trino yet and step 3 restarts it anyway,
  so carry on and do not trust Trino's numbers until then.
- This shell has no `CATALOG_TYPE`: `env | grep CATALOG_TYPE` prints nothing. Compose takes a
  variable from the shell over `.env`, so never source `.env` here; the commands below read single
  values with `sed`.
- The image matches the tree:
  `docker compose --env-file .env -f docker/compose.yaml --profile core build spark-bronze`.
  The running bronze keeps its image until step 3 recreates it.

## Helpers

Paste at the repo root. All three only read; `cutover` collects this run's logs outside the repo.

```bash
cutover=~/lakehouse-cutover; mkdir -p "$cutover"

# Lakekeeper's current metadata file of every bronze and silver table (one page holds them all).
lk_pointers() {
  python3 - <<'PY'
import json, urllib.request
api = "http://127.0.0.1:8181/catalog/v1"
def get(path):
    with urllib.request.urlopen(api + path, timeout=30) as response:
        return json.load(response)
prefix = get("/config?warehouse=lake")["defaults"]["prefix"]
for ns in ("bronze", "silver"):
    for ident in get(f"/{prefix}/namespaces/{ns}/tables")["identifiers"]:
        table = get(f"/{prefix}/namespaces/{ns}/tables/{ident['name']}?snapshots=refs")
        print(f"{ns}.{ident['name']} {table['metadata-location']}")
PY
}

# The same for the JDBC catalog, in a read-only transaction.
jdbc_pointers() {
  docker compose --env-file .env -f docker/compose.yaml exec -T \
    -e PGOPTIONS='-c default_transaction_read_only=on' postgres-meta \
    psql -U "$(sed -n 's/^META_USER=//p' .env)" -d "$(sed -n 's/^CATALOG_DB=//p' .env)" \
    -v ON_ERROR_STOP=1 -At -F ' ' -c \
    "select table_namespace || '.' || table_name, metadata_location from iceberg_tables
     where catalog_name = 'lake' and table_namespace in ('bronze', 'silver')"
}

# Row count and current main snapshot of every table in the register log, through Trino `lake`.
table_numbers() {
  local sql="" t
  for t in $(sed -n 's/^same \([^ ]*\) .*/\1/p' "$cutover/register.log"); do
    sql+="${sql:+ union all }select '$t', count(*), (select snapshot_id from ${t%%.*}.\"${t#*.}\$refs\"
      where name = 'main') from $t"
  done
  docker exec lakehouse-trino-1 trino --catalog lake --output-format TSV --execute "$sql order by 1"
}
```

## 1. Stop the writers and register

```
docker stop lakehouse-spark-bronze-1
docker ps --format '{{.Names}}' | grep spark                   # prints nothing
bash scripts/lakekeeper/register.sh | tee "$cutover/register.log"; echo "rc=${PIPESTATUS[0]}"
table_numbers > "$cutover/numbers-before.tsv"                  # Trino still on JDBC
```

Expected: nine `same <table> <metadata file>` lines, `all 9 tables point at the same metadata file
in both catalogs` and `rc=0`. The `same` lines are the rollback point in readable form. On a
refusal or `MISMATCH`: `docker start lakehouse-spark-bronze-1` and stop here. Lakekeeper's
pointers are inert while nothing reads them.

## 2. Check the config

```
git status --short docker/compose.yaml docker/trino/etc/catalog/lake.properties
docker compose --env-file .env -f docker/compose.yaml --profile core --profile query config -q
```

Before the cutover commit both files show as modified; after it, nothing. `config -q` prints
nothing.

## 3. Switch

```
sed -i 's/^CATALOG_TYPE=jdbc$/CATALOG_TYPE=rest/' .env && grep '^CATALOG_TYPE=' .env
docker compose --env-file .env -f docker/compose.yaml --profile core config spark-bronze | grep CATALOG_TYPE
docker compose --env-file .env -f docker/compose.yaml --profile core --profile query up -d spark-bronze trino
docker restart lakehouse-trino-1
```

Both greps print `rest`. `up` runs the one-shots again, all idempotent (`minio-init`,
`lakekeeper-migrate`, `lakekeeper-bootstrap`, whose log says `warehouse lake exists`), recreates
`spark-bronze` for its new `CATALOG_TYPE`, and leaves `trino` `Running`: its config did not
change, because `lake.properties` is a bind mount and compose leaves `depends_on` out of the config
hash (checked with `--dry-run` on compose 5.5.1). Hence the explicit restart. Never `make up` here:
it starts the replayer container as well.

If `up` fails on a dependency (Lakekeeper unhealthy, bootstrap failed), bronze is down and nothing
has gone through Lakekeeper: take the free rollback.

## 4. Check

### 4a. Before any write through Lakekeeper

```
docker logs lakehouse-spark-bronze-1 2>&1 | grep 'Resuming at batch'
docker exec lakehouse-spark-bronze-1 printenv CATALOG_TYPE
docker logs lakehouse-trino-1 2>&1 | grep -P 'catalog\.lake\t+iceberg\.catalog\.type\s' | tail -1
table_numbers > "$cutover/numbers-after.tsv"
diff "$cutover/numbers-before.tsv" "$cutover/numbers-after.tsv"
make silver
diff <(sed -n 's/^same //p' "$cutover/register.log" | LC_ALL=C sort) <(lk_pointers | LC_ALL=C sort)
```

Expected: `Resuming at batch N` with the batch bronze stopped at, `rest`, a Trino line ending in
`REST`, both diffs empty. Bronze turns healthy within 2 minutes
(`docker inspect -f '{{.State.Health.Status}}' lakehouse-spark-bronze-1`). `make silver` finds no
new bronze snapshot, so it commits nothing. If the last diff shows a silver table, silver did
commit through Lakekeeper, and from here the paid rollback applies. Any other failed check: free
rollback.

### 4b. The first commit through Lakekeeper

From here on the free rollback is gone.

```
bash -c '. scripts/chaos/lib.sh && no_other_replayer && replay_burst 120'
bash -c '. scripts/chaos/lib.sh && wait_until 600 "bronze to catch up" bronze_caught_up'
diff <(sed -n 's/^same //p' "$cutover/register.log" | LC_ALL=C sort) <(lk_pointers | LC_ALL=C sort)
diff <(sed -n 's/^same //p' "$cutover/register.log" | LC_ALL=C sort) <(jdbc_pointers | LC_ALL=C sort)
make silver
bash -c '. scripts/chaos/lib.sh && bronze_offsets_report && reconcile'
```

`replay_burst 120` plays one virtual day at speed 720. The first diff shows `bronze.cdc_events` at a
new metadata file: Lakekeeper's first live write into an `s3a://` table. The second diff is empty:
JDBC was not touched. `bronze_offsets_report` shows 0 duplicates and 0 missing in every partition,
and `reconcile` prints `ok` for every table; both read through Trino `lake`, which is Lakekeeper
now. A failure here is fixed forward or rolled back by the owner (paid rollback).

## 5. Protect bronze and silver

```
bash scripts/lakekeeper/protect.sh
```

Expected: `protected <table> <table-uuid>` for each bronze and silver table, then `all 9 bronze and
silver tables are protected`; a second run prints `already protected` for each. The script reads
every flag back, so never test protection with a DROP. If time runs out before this step, it is
the first line of `docs/HANDOFF.md`.

## 6. Measure

```
docker stats --no-stream lakehouse-lakekeeper-1
docker compose --env-file .env -f docker/compose.yaml exec -T postgres-meta \
  psql -U "$(sed -n 's/^META_USER=//p' .env)" -d "$(sed -n 's/^LAKEKEEPER_DB=//p' .env)" \
  -Atc "select pg_size_pretty(pg_database_size(current_database()))"
```

Before the cutover: 87.5 MiB of 256 MiB, and 12 MB. Bronze commits every 20 s, and each commit now
writes `postgres-meta` too. Record both numbers in `OPERATIONS.md` and compare a day later.

## After the cutover

- Lakekeeper is the catalog. The JDBC rows in `iceberg_catalog` keep the pre-cutover pointers as
  the rollback point until the end of week 3; nothing writes them.
- Never start a Spark job with `CATALOG_TYPE=jdbc`, whether in `.env`, as `-e CATALOG_TYPE=jdbc`
  or exported in a shell, except through the rollback below. The JDBC rows point at the
  pre-cutover snapshots while bronze's checkpoint is past every commit made through Lakekeeper: the
  job would commit on top of the old snapshot, the events committed through Lakekeeper would never
  reach that history, and the two catalogs would fork. Each side would then hold snapshots and
  files the other does not know, and `expire_snapshots` or `remove_orphan_files` on one side would
  delete files the other still reads.
- The same goes for Trino: the JDBC `lake.properties` comes back only with the rollback. On JDBC,
  a Trino `DROP TABLE` deletes the table's directory at once.
- `register.sh` refuses once `CATALOG_TYPE` is `rest`: registering again would replace the live
  pointers with the old JDBC ones. Do not work around it.
- On Lakekeeper a drop deletes files (`OPERATIONS.md`, "What deletes files"); protection stops it
  for bronze and silver.

## Rollback

Stop the writers first, then see which side of the first commit you are on:

```
docker stop lakehouse-spark-bronze-1                           # and no make silver running
diff <(jdbc_pointers | LC_ALL=C sort) <(lk_pointers | LC_ALL=C sort)
```

Empty: nothing was committed through Lakekeeper, take the free path. Any line: the paid path.

### Free: before the first commit through Lakekeeper

```
sed -i 's/^CATALOG_TYPE=rest$/CATALOG_TYPE=jdbc/' .env && grep '^CATALOG_TYPE=' .env
git show 5cf0fec:docker/trino/etc/catalog/lake.properties > docker/trino/etc/catalog/lake.properties
docker compose --env-file .env -f docker/compose.yaml --profile core up -d --no-deps spark-bronze
docker restart lakehouse-trino-1
```

`5cf0fec` (`lake: lakekeeper side by side, tables registered`) is the last commit with the JDBC
`lake.properties`. `--no-deps` keeps a broken Lakekeeper from blocking bronze. Checks: `Resuming at
batch` in bronze's log, `printenv CATALOG_TYPE` says `jdbc`, Trino's catalog line ends in `JDBC`,
and `table_numbers` equals `numbers-before.tsv`. Lakekeeper can keep running: its rows stay inert
next to a JDBC Spark. A new attempt starts again at step 1.

### Paid: after the first commit through Lakekeeper (owner only)

DML on `iceberg_catalog` is on the blast-radius list: the owner runs it, or gives an explicit ok
for this run. Each JDBC row takes over Lakekeeper's current pointer, so bronze's checkpoint and
the table history stay consistent.

1. Writers stay stopped: bronze stopped, no `make silver`, nothing writing through Trino (from
   week 3, stop `orchestrate`). Save what Trino sees on Lakekeeper:
   `table_numbers > "$cutover/numbers-rest.tsv"`.
2. Write the statements, then read them:

   ```
   jdbc_pointers | LC_ALL=C sort > "$cutover/jdbc-now.txt"
   lk_pointers | LC_ALL=C sort > "$cutover/lakekeeper-now.txt"
   awk -v q="'" '
     NR == FNR { jdbc[$1] = $2; next }
     !($1 in jdbc) { print "-- only in Lakekeeper, register it instead: " $1 " " $2; next }
     jdbc[$1] != $2 {
       split($1, t, ".")
       print "update iceberg_tables set previous_metadata_location = metadata_location,"
       print "  metadata_location = " q $2 q
       print "where catalog_name = " q "lake" q " and table_namespace = " q t[1] q " and table_name = " q t[2] q
       print "  and metadata_location = " q jdbc[$1] q ";"
     }' "$cutover/jdbc-now.txt" "$cutover/lakekeeper-now.txt" > "$cutover/rollback.sql"
   cat "$cutover/rollback.sql"
   ```

   One `update` per table whose pointer moved. Each applies only while the JDBC row still holds
   the pointer just read.
3. Apply in one transaction and compare:

   ```
   docker compose --env-file .env -f docker/compose.yaml exec -T postgres-meta \
     psql -U "$(sed -n 's/^META_USER=//p' .env)" -d "$(sed -n 's/^CATALOG_DB=//p' .env)" \
     -v ON_ERROR_STOP=1 --single-transaction < "$cutover/rollback.sql"
   diff <(jdbc_pointers | LC_ALL=C sort) <(lk_pointers | LC_ALL=C sort)
   ```

   Expected: `UPDATE 1` per statement and an empty diff. `UPDATE 0` means that row changed after
   step 2: find out why, then write and apply the statements again (rows already updated no
   longer differ).
4. Run the free path's four commands and its checks, except that `table_numbers` must now equal
   `numbers-rest.tsv`.
5. A table that exists only in Lakekeeper (a `-- only in Lakekeeper` line, or a table in another
   namespace such as `gold` from week 3) is registered in JDBC from a Spark session on
   `CATALOG_TYPE=jdbc`: `CALL lake.system.register_table(table => '<ns>.<table>', metadata_file =>
   '<metadata file>')`. The shared Spark conf maps `s3://` to S3A, so its paths stay readable.
   `lake.demo` is a sandbox: skip it.

After a paid rollback Lakekeeper's rows fall behind JDBC with the first JDBC commit, and they keep
`protected`. A new cutover starts at step 1, and `register.sh` then fails with 409 on every
protected table: removing protection is on the blast-radius list, so the owner decides. A table
registered again comes back unprotected, so step 5 runs again.
