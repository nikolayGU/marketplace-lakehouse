# Evidence

What was run, when, and what it showed. Every number carries a date (UTC unless noted) and a
source: a section of [OPERATIONS.md](../OPERATIONS.md), a file, a GitHub run or a command that
anyone with the stack up can repeat. Anything not run live is marked `not proven`.

Contents: [Reconciliation](#reconciliation-source-against-silver) |
[MinIO probe](#probe-minio-stopped) | [Failure scenarios](#failure-scenarios) | [Maintenance](#maintenance-before-and-after) |
[Alerts](#alerts-and-time-to-fire) | [CI and smoke](#ci-and-smoke) | [Dashboard](#dashboard) |
[Trino access control](#trino-access-control) | [Superset and local access](#superset-and-local-access) |
[Not proven](#not-proven-yet) | [How it was built](#how-it-was-built)

## Reconciliation: source against silver

`make reconcile` compares Postgres with the live rows of silver for all seven tables: row count,
set of primary keys, sum of every decimal column (`scripts/chaos/lib.sh`, `scripts/reconcile_sql.py`),
and since 2026-10-30 the row fingerprint of every contract column that `dq_checks` uses, printed
as a last `values` column (`ok` or `DIFF`). It only reads. Output of 2026-10-29 18:50 UTC, before the fingerprint,
run for this page:

```
customers    postgres    99441  silver    99441  rows ok   keys ok   sums -
order_items  postgres   109081  silver   109081  rows ok   keys ok   sums ok (13173478.80 2182507.96)
orders       postgres    96258  silver    96258  rows ok   keys ok   sums -
payments     postgres   100623  silver   100623  rows ok   keys ok   sums ok (15530922.11)
products     postgres    32951  silver    32951  rows ok   keys ok   sums -
reviews      postgres    93494  silver    93494  rows ok   keys ok   sums -
sellers      postgres     3095  silver     3095  rows ok   keys ok   sums -
```

With the `values` column (the row fingerprint, commit `8164afe`, audit B2): `make verify-fast` of
2026-10-30 16:37 UTC, HEAD `ea64b6e` (stamp `fast at 2026-10-30T16:37:13Z`). `verify-fast` only
reads: it does not run `make silver`. The block above stays as the record before the fingerprint.
Output as printed:

```
customers    postgres    99441  silver    99441  rows ok   keys ok   sums -  values ok
order_items  postgres   109081  silver   109081  rows ok   keys ok   sums ok (13173478.80 2182507.96)  values ok
orders       postgres    96258  silver    96258  rows ok   keys ok   sums -  values ok
payments     postgres   100623  silver   100623  rows ok   keys ok   sums ok (15530922.11)  values ok
products     postgres    32951  silver    32951  rows ok   keys ok   sums -  values ok
reviews      postgres    93494  silver    93494  rows ok   keys ok   sums -  values ok
sellers      postgres     3095  silver     3095  rows ok   keys ok   sums -  values ok
verify ok
```

Both `verify` targets add the bronze check to `reconcile` (every Kafka offset exactly once, all
seven tables present) and end with `verify ok`; `make verify` first runs one silver merge. A full
run that this page records: `verify ok`, 2026-10-29 19:16 UTC, before commit `46f5282` (the W6-T11 check, [Trino access control](#trino-access-control)).
`dq_checks` repeats the comparison every 15 minutes and also compares row fingerprints source to
silver and silver to gold (`reconcile_values`); its run at 16:45 on 2026-10-29 had every
`reconcile_*_differing` at 0 and `reconcile_in_flight` at 0 ([First live run, step 11](#first-live-run-2026-10-29)).

## Probe: MinIO stopped

A live probe of the third `verify` check, not a chaos scenario (commit `2b0fce1`, 2026-11-05).
`docker stop lakehouse-minio-1` at 16:54:53 UTC, then `VERIFY_WAIT=60 timeout -k 5 120 make
verify-fast`: exit 2 after 11.7 s with `verify failed: Trino and catalog lake answer, but the object
store (MinIO) fails: curl: (6) Could not resolve host: minio`. `docker start` at 16:55:15, so MinIO
was down 22 s; healthy at 16:55:27, and `verify-fast` ended `verify ok`. With Lakekeeper stopped
(2026-11-04) the refusal took 11 s, about 9 s of it the Trino REST client giving up; with
`TRINO_PROBE_WAIT` below about 10 the same fault reads as `does not answer within N s`. Why the third probe exists
and what a paused MinIO would read as: [OPERATIONS, Daily commands](../OPERATIONS.md#daily-commands).

## Failure scenarios

Each scenario is `make chaos-<name>` ([`scripts/chaos/`](../scripts/chaos)) and ends in a check that
fails on any duplicate or missing Kafka offset or any difference from Postgres. Full write-ups:
what happened, what monitoring shows, data at risk, recovery, why nothing is lost.

| # | Scenario | Date | Measured | Write-up |
|---|---|---|---|---|
| 1 | Spark bronze killed mid-batch | 2026-10-07 | Kill 18:09:44 during batch 80 (158 records), replayed batch committed 18:10:12, 28 s after the kill, same query id; 0 duplicate or missing offsets in 21 topic partitions, no epoch committed twice | [1](failure-scenarios.md#1-spark-bronze-killed-mid-batch) |
| 2a | Kafka Connect restart | 2026-10-07 | Recovered in about 32 s; 1429 CDC events in the minute before the restart, 1593 after; 0 events repeated with the same LSN; silver matches Postgres (rows, keys, sums) for 7 tables | [2a](failure-scenarios.md#2a-kafka-connect-restart) |
| 2b | Kafka Connect killed | 2026-10-07 | Connector resumed 26 s after `docker start`; 253 events arrived twice (orders 173, order_items 40, payments 39, reviews 1), all absorbed; silver matches Postgres (rows, keys, sums) for 7 tables | [2b](failure-scenarios.md#2b-kafka-connect-killed) |
| 3 | Duplicate events from the source | 2026-10-07 | 2267 CDC events in the window, 95 no-op repeats (9.8% of status UPDATEs, 90 of 926 orders); 0 changes arrived twice with the same LSN; silver matches Postgres (rows, keys, sums); script 3 min 11 s | [3](failure-scenarios.md#3-duplicate-events-from-the-source) |
| 4 | Late events | 2026-10-07 | An old change re-sent after a newer one; silver kept `approved` and `_last_lsn` 1401679552 before and after (the MERGE guard dropped it); bronze kept the copy at a new offset; script 3 min 12.6 s | [4](failure-scenarios.md#4-late-events) |
| 5 | PostgreSQL restart | 2026-10-23 | Postgres healthy in 13 s, connector streamed again 13 s later without a failed task; bronze caught up 28 s after a 30 s burst; `ContainerRestarting` firing 15 s after the restart; `reconcile` 7 of 7 | [5](failure-scenarios.md#5-postgresql-restart) |
| 6 | Connector stopped for 30 minutes (WAL growth) | 2026-10-23, 2026-10-29 | 2026-10-23: `ConnectorNotRunning` 95 s after the stop, `SlotWalRetainedHigh` 326 s after it, 80.9 MB held. 2026-10-29 (committed script, full hold): connector stopped 17:47:02 to 18:17:06, `dq_checks` at 18:00 and 18:15 green with `in flight: CDC stands, no verdict`, `CdcStalledSourceWrites` firing 18:20:04, then silver matches Postgres (rows, keys, sums) 7 of 7, exit 0. Sources for the 2026-10-29 run: the result of W6-T07 in [the W6 spec](planning/14-closeout-spec.md) and the approval log entry of 29.10 18:22 in [HANDOFF](HANDOFF.md) (ru) | [6](failure-scenarios.md#6-connector-stopped-for-30-minutes-wal-growth) |
| 7 | Corrupted event in topic | 2026-10-23 | One non-envelope record: one `silver.quarantine` row after the first merge, still one after the second; the rest of the batch merged | [7](failure-scenarios.md#7-corrupted-event-in-topic) |
| 8 | Kafka down for 6 minutes | 2026-10-23 | Kafka healthy 20 s after the start, connector `RUNNING` after 20 s, bronze caught up after 25 s; `spark-bronze` restarted 15 times, resumed from the checkpoint each time; 21 partitions without duplicate or missing offset; silver matches Postgres (rows, keys, sums) 7 of 7; `SparkNoBatch5m` did not fire (see Alerts) | [8](failure-scenarios.md#8-kafka-down-for-6-minutes) |
| 9 | Airflow task failure (dbt test) | 2026-10-18 (run), 2026-10-23 (alert) | `dbt_build` red on a broken test, children skipped, `mart_daily_sales` kept its 9 snapshots; `AirflowDagFailed` 17 s after the red run ended | [9](failure-scenarios.md#9-airflow-task-failure-dbt-test) |
| 10b | Silver merge killed between two tables | 2026-11-06 | `lakehouse-silver-merge` killed 12:10:23 after the first of 4 tables (`order_items`, 97 events); 3 tables differed from Postgres right after; the Airflow retry (`merge` try 2, 12:11:24 to 12:11:49) brought silver level about 86 s after the kill; run `success` 12:11:50 (REST), so `AirflowDagFailed` did not fire; `ContainerRestarting` firing (`activeAt` 12:11:34); `reconcile` 7 of 7 | [10b](failure-scenarios.md#10b-silver-merge-killed-between-two-tables) |

The 2026-10-23 run of
scenario 6 used an uncommitted script version whose logical-message padding of the WAL stopped CDC for about 8 minutes
with no loss; it is described in the write-up, together with the fix.

## Maintenance, before and after

Design of the procedures: ADR-025 in [DECISIONS.md](../DECISIONS.md).

The MinIO image swap of the same day (the images are built from source, ADR-026): bucket 4045
objects and 482 441 040 bytes before and after (`mc du --json`), `mc admin info` version
2025-09-07T16:13:09Z before and after, `make verify-fast` `verify ok`
([W6-T00 result](planning/14-closeout-spec.md)).

### First live run, 2026-10-29

Everything below is UTC and comes from the command output of that day. The image
`lakehouse/spark:dev` (72e423bd) was built at 16:05 from a clean HEAD (3a213c6); its code is the
same as `streaming/spark_jobs` (sha256 diff). Steps 5 to 10 ran as manual writes: `silver_upsert`
and `dbt_build` paused and finished, scheduler stopped, one command, scheduler started (windows
16:21-16:26, 16:28-16:30 and 16:33). Order of the steps:

1. Baseline (16:07): `bronze_caught_up` and `bronze_offsets_ok` exit 0; 4821 objects,
   877 765 423 bytes under `warehouse/`.
2. Copy (16:12): `mc mirror` of `warehouse/` to `/mnt/d/lakehouse-backup/warehouse-20261029`
   (outside the repo). The host holds 4821 files and 877 765 423 bytes (`find`, `du -sb
   --apparent-size`), equal to `mc du --json` and `mc ls --json`. This is a one-off copy before the
   first deletion, not a regular backup.
3. Demo (16:13-16:15): `iceberg_demo` compacted `lake.demo.orders` from 21 files to 1
   (156 027 to 77 927 bytes); its expire deleted 22 data files, 43 manifests and 22 manifest lists
   and left 1 snapshot. Then `maintenance expire --days 7 demo.orders` exited 0 with all counts 0.
4. `spark-bronze` recreated alone (16:17): the 20 other containers kept their `Created` time;
   healthy after 26 s, 0 restarts, log `Resuming at batch 171`, and `bronze."cdc_events$properties"`
   has `write.metadata.delete-after-commit.enabled = true`. Rows (558 629) and `max(kafka_offset)`
   (77 659) did not move.
5. Bronze compaction (`rewrite-data --before-today`).
6. `silver.sellers` expire.
7. Expire of the other eight silver tables, one run.
8. Expire of the nine gold tables, one run.
9. Orphans dry runs, four runs: `demo`, silver, gold, bronze with `--location-suffix metadata`.
10. Review of the candidates (below), then the real orphans run on bronze `metadata/` only.
11. `make replay-burst SECONDS=60` (virtual time 2026-07-16 21:33:42 to 2026-07-17 09:29:04, 233
    events, 76 858 to 77 091 emitted, 22 060 pending), then the normal pipeline: `silver_upsert`
    (16:40 and 16:45) and `dbt_build` (16:40) success, `dq_checks` (16:45) success with
    `reconcile_in_flight` 0, every `reconcile_*_differing` 0 and `tables_differing{at_rest=true}` 0.
12. `iceberg_maintenance` unpaused (16:46). First scheduled run `scheduled__2026-10-29T03:30`
    success: `expire_and_compact=False`, so `expire_silver`, `gold_expire_commands`, `expire_gold`,
    `compact_bronze` and `rewrite_position_deletes` were skipped and `optimize` ran for 8 tables.
    `make reconcile` 7/7 afterwards. `iceberg_orphans` stays paused.

Before and after. The row count of every table was equal before and after, and `make reconcile`
passed 7/7 after the silver expire.

| Table | Snapshots | Data files deleted | Manifests deleted | Manifest lists deleted |
|---|---|---|---|---|
| `bronze.cdc_events` (compaction) | 171 to 172 (one `replace`) | 589 rewritten (46 048 268 bytes) into 24 | not run | not run |
| `silver.sellers` | 2 to 1 | 4 | 1 | 1 |
| `silver.customers` | 4 to 1 | 12 | 3 | 3 |
| `silver.order_items` | 31 to 13 | 68 | 40 | 18 |
| `silver.orders` | 38 to 15 | 51 (and 111 position-delete files) | 69 | 23 |
| `silver.payments` | 31 to 13 | 68 | 34 | 18 |
| `silver.products` | 4 to 1 | 12 | 3 | 3 |
| `silver.reviews` | 23 to 7 | 54 | 38 | 16 |
| `silver.quarantine` | 5 to 1 | 3 | 6 | 4 |
| `silver.orders_per_minute` | 15 to 15 | 0 | 0 | 0 |
| `gold.category_translation` | 82 to 32 | 25 | 49 | 50 |
| `gold.dim_customers` | 41 to 16 | 25 | 25 | 25 |
| `gold.dim_products` | 41 to 16 | 25 | 25 | 25 |
| `gold.dim_sellers` | 41 to 16 | 25 | 25 | 25 |
| `gold.fct_order_items` | 38 to 15 | 23 | 23 | 23 |
| `gold.fct_orders` | 41 to 16 | 25 | 25 | 25 |
| `gold.mart_daily_sales` | 33 to 24 | 0 | 0 | 9 |
| `gold.mart_delivery_sla` | 36 to 15 | 21 | 21 | 21 |
| `gold.mart_seller_performance` | 36 to 15 | 21 | 21 | 21 |

Only `silver.orders` had position-delete files to delete; every other silver table reported 0.
After the expire, no table has more than 1 snapshot older than 7 days in silver (`customers`,
`products` and `sellers`: their only snapshot), and none in gold. `silver.orders_per_minute` kept all
15 snapshots; its last commit was 2026-10-23 19:23:02 before and after.

Bronze, before and after the compaction and the real orphans run:

| Measure | Before | After |
|---|---|---|
| Data files in partitions before today (`$files`) | 595 in 27 partitions | 30 |
| Rows, `max(kafka_offset)` | 558 629, 77 659 | equal |
| Kafka end offsets (md5) | | equal, `bronze_offsets_ok` 0 |
| Objects in `bronze/data/` | 619 | 619 |
| Objects in `bronze/metadata/` | 465 | 444 |
| `metadata.json` objects | 122 | 101 |

Orphans. Dry runs found 0 candidates for `demo`, 0 for the 9 silver tables, 0 for the 9 gold tables,
and 21 for bronze `metadata/` (`files_truncated` false). The review before the real run: all 21 are
`metadata/00000` to `00020` `*.metadata.json` files written 2026-09-22 19:22-19:43; none appears in
`$metadata_log_entries` (101 rows), `$snapshots.manifest_list` (172) or `$all_manifests` (171); the
JDBC pointer of bronze is `00121`, which is not a candidate. The real run removed 21 files, the same
set as the dry run, and left `bronze/data/` at 619 objects.

Time of each procedure, read from the first Spark log line to the end of the command, so the
figures are approximate. No separate time was recorded for `mc mirror` and the demo; their windows
are in the list above.

| Procedure | Time |
|---|---|
| `spark-bronze` recreate to healthy | 26 s |
| Bronze compaction (`rewrite-data --before-today`) | about 16 s from the first Spark log line |
| `silver.sellers` expire | about 10 s from the first Spark log line |
| Expire of the other eight silver tables, one run | about 34 s from the first Spark log line |
| Expire of the nine gold tables, one run | about 40 s from the first Spark log line |
| Orphans dry run (each of four runs) | 9 to 23 s |
| Real orphans run, bronze `metadata/` | about 13 s from the first Spark log line |

Rollback point. The owner released the JDBC rollback point on 2026-10-29; the rows of `iceberg_catalog` were not deleted.

### Orphans next to orders_per_minute, 2026-10-30

The table location `s3a://lakehouse/warehouse/silver/orders` is a string prefix of
`silver/orders_per_minute-01a169dd-...`, so a listing by prefix would see the files of the other
table. `$C maintenance orphans silver.orders` (dry run) at 17:48 UTC, `older_than` 2026-10-23
17:48:44: `{"candidates":0,"dry_run":true,"files":[],"files_truncated":false}`. The first snapshot
of `orders_per_minute` (2026-10-23 17:45:11, `append`, 3 data files) is older than that and still
live, so its files were old enough to show up: the procedure lists the table directory, not the
string prefix.

## Alerts and time to fire

16 rules in [`observability/prometheus/alerts.yml`](../observability/prometheus/alerts.yml) (13 named
alerts, three of them with two expressions), tested by `make alerts-test` (promtool; `SUCCESS: 16 rules found`, 2026-11-06; it was 15 rules on 2026-10-30, before `GoldStaleAtRest`; failure cases first). No Alertmanager
(ADR-023): the alerts are read in Prometheus and in the Grafana "Firing alerts" panel. The table is
in [OPERATIONS, Alerts](../OPERATIONS.md#alerts).

| Alert | Shown how | Time to fire |
|---|---|---|
| `ConnectorNotRunning` | live, scenario 6 (2026-10-23) | 95 s after the connector stop |
| `SlotWalRetainedHigh` | live, scenario 6 (2026-10-23) | 326 s after the stop, 80 MB held |
| `SparkNoBatch5m` | live, `spark-bronze` stopped (2026-10-23) | 315 s after the stop (`cause="gone"`) |
| `FreshnessAbove15m` | live, `silver_upsert` paused, burst (2026-10-23) | 1561 s after bronze caught up (900 s plus up to 15 min until the next `dq_checks`) |
| `AirflowDagFailed` | live, scenario 9 (2026-10-23) | 17 s after the red run ended |
| `ContainerRestarting` | live, scenarios 5 and 8 (2026-10-23) | 15 s after the restart |
| `CdcStalledSourceWrites` | promtool (two runs, one run, short history); live, scenario 6 (2026-10-29) | firing 18:20:04, 33 min after the stop (17:47:02 to 18:20:04): two `dq_checks` runs with stalled 1, then the 20 min window; `cdc_stalled` was 1 from 18:01 (W6-T07 result in [the W6 spec](planning/14-closeout-spec.md), [HANDOFF](HANDOFF.md) log 29.10 18:22) |
| `SparkRestartLoop` | rule run over the stored data of scenario 8 (TSDB replay), not a live firing | true from 17:11:15, 51 s after the first restart (17:10:24); the 2026-10-23 rule was not loaded then |
| `FreshnessAbove15m` with `cause="unknown"`, `SlotWalHeldIdle`, `DqChecksStale`, `ScrapeTargetDown`, `SilverGoldNotCompared`, `GoldStaleAtRest` | promtool only | not shown live |

`GoldStaleAtRest` (audit of 2026-11-06) exists because of a finding that was live: Airflow 3.3 queues
no Asset event for a paused DAG (`airflow/assets/manager.py:354` in the image), so the `lake.silver`
event of 12:11:49 UTC on 2026-11-06, which came while `dbt_build` was paused during chaos 10b, created
no `dbt_build` run and gold stayed behind silver. The rule fires when `dq_checks` finds that state at
rest on two runs in a row. It compares commit times of Iceberg snapshots, not the snapshot dbt read,
and `expire_silver` after `optimize` can remove the newest data snapshot; both only miss an alert.

`SparkNoBatch5m` did not fire in scenario 8: a crash-looping driver dies before its first batch and
Kafka came back inside the 5 minutes of the `gone` rule. That gap is why `SparkRestartLoop` exists
([failure scenario 8](failure-scenarios.md#8-kafka-down-for-6-minutes)).

## CI and smoke

| Run | What | Result |
|---|---|---|
| [ci 40934002684](../../../actions/runs/40934002684) | push to `main`, HEAD `6ca7224`, 2026-10-29 | success |
| [ci 40924192138](../../../actions/runs/40924192138) | push, `649cb68`, 2026-10-29 | success |
| [smoke 40907438614](../../../actions/runs/40907438614) | `workflow_dispatch`, `664a7e6`, 2026-10-29, first green run on the source-built MinIO images | success, 10 min 1 s |
| [smoke 40916528470](../../../actions/runs/40916528470) | `workflow_dispatch`, `f71eab2`, 2026-10-29 | success, 9 min 14 s |
| [smoke 40934001854](../../../actions/runs/40934001854) | `workflow_dispatch`, `6ca7224`, 2026-10-29 | success, 10 min 52 s |
| [ci 40897412910](../../../actions/runs/40897412910) | push, `f206596`, 2026-10-29 | failure, job `spark-tests` only (below) |
| [smoke 40290595866](../../../actions/runs/40290595866) | Monday schedule, 2026-10-26 | failure at `make start`: the MinIO images were gone from quay.io and Docker Hub |

`smoke.yml` walks the clean-clone path on the committed sample: `make secrets`, `make bootstrap`, a
60 s `make replay-burst`, `make verify`, and a second `make bootstrap` that must say `replay state
exists, load skipped` and end `verify ok`. It builds the Spark, Connect, MinIO and `mc` images from
scratch, so it is cold every time. The weekly schedule (Monday 03:00 UTC) is back since the first
green run; its scheduled runs are green: [smoke 41430931906](../../../actions/runs/41430931906) on
2026-11-02 (HEAD `4b65cd7`) and [smoke 42606043447](../../../actions/runs/42606043447) on 2026-11-09
(HEAD `4169df6`).

The red `spark-tests` run is a defect that CI caught and local checks did not: a test held a fixed
clock (`2026-10-23 03:30 UTC`) and failed on every run after 2026-10-24 03:30 UTC. The fix (the
real clock) is in `eebb639`, green in [ci 40901323188](../../../actions/runs/40901323188).

Checks of record: `make check` 1879 passed, commit `22a8748`, 2026-11-10, local
([HANDOFF](HANDOFF.md); Spark tests skip on a host without a JVM); the Spark tests in the image,
239 passed, job `spark-tests` of [ci 42848376843](../../../actions/runs/42848376843) on `63e5650`,
2026-11-10 (a skip there is a failure). Job list and what each runs:
[OPERATIONS, CI](../OPERATIONS.md#ci).

## Dashboard

The "Marketplace" dashboard (Grafana, Trino datasource plugin 1.4.1) shows four panels over
gold only: daily sales, GMV by category, delivery SLA by state, cancellations. The panels read
`lake_ro.gold` since W6-T11 (commit `46f5282`, [below](#trino-access-control)); the screenshot of
2026-10-29 18:44 UTC and the checks below were taken before that switch, when they read `lake.gold`:

![Marketplace dashboard](img/marketplace-dashboard.png)

Checks of 2026-10-29, before the switch ([W6-T01 result](planning/14-closeout-spec.md), [OPERATIONS, Dashboards](../OPERATIONS.md#dashboards)):

- `uv run python scripts/obs/check_dashboards.py observability/grafana/dashboards/marketplace.json`
  prints `queries ok: 4`; through `/api/ds/query` the panels returned 600, 10, 27 and 600 rows.
- The orders panel shows 96 163 orders and `select count(*)` on `fct_orders` gives 96 163. Summing
  `orders_count` of `mart_daily_sales` would give 96 650, because the mart counts an order in each
  of its states per seller state; the reviewer found this double count before the dashboard was
  accepted.
- GMV by category adds up to 13 086 460.39, equal to `sum(gmv)` of the mart.
- Grafana used 276.7 MiB of its 384 MiB limit.
- After the switch to `lake_ro.gold`, `uv run python scripts/obs/check_dashboards.py` (all
  dashboards) prints `queries ok: 39` (2026-10-29, 19:16).

## Trino access control

W6-D17, card W6-T11, commit `46f5282`. Trino has file-based access control
(`docker/trino/etc/access-control.properties`, `docker/trino/etc/rules.json`) and a second catalog
`lake_ro` (`docker/trino/etc/catalog/lake_ro.properties`, `iceberg.security=read_only`) over the
same warehouse. The `grafana` user, used by the Grafana datasource and by `check_dashboards.py`,
reads `lake_ro.gold` only. Live probes of 2026-10-29 after `docker restart lakehouse-trino-1` at
19:15, run as the user named:

| User | Statement | Result |
|---|---|---|
| `grafana` | `select` from `lake_ro.gold.fct_orders` | 96 258 |
| `grafana` | `select` from `lake_ro.silver` | Access Denied |
| `grafana` | any query on catalog `lake` or `system` | Access Denied |
| `grafana` | `create table` | Access Denied |
| `grafana`, `dbt` (through `lake_ro`) | `optimize` on a gold table | `Cannot execute table procedure OPTIMIZE` |
| `dbt`, `trino`, `airflow` | `select` from `lake.silver.orders` | 96 258 |

Afterwards: `make dbt-build` `PASS=68 WARN=4 ERROR=0` (19:16), `check_dashboards.py` `queries ok: 39`,
`make verify` `verify ok` (19:16, before the commit). Residual risk, recorded in
[OPERATIONS, Access control](../OPERATIONS.md#access-control): Trino has no authentication, so the
user name is only a label; a Grafana admin who adds a datasource with another user, or a client
that reaches port 8080, gets that user's rights. The rules protect the provisioned datasource,
not a person with an admin login, a shell or network access.

## Superset and local access

Profile `bi` (2026-11-06): `superset-init` (one-shot: migration, `admin`, import of the bundle in
[`docker/superset/dashboards`](../docker/superset/dashboards)), `superset` and `superset-mcp`
([OPERATIONS, Superset](../OPERATIONS.md#superset-profile-bi)). Checks on the running stack:

| Check | Result |
|---|---|
| `docker exec lakehouse-superset-1 python /app/check.py` (15:52 UTC), every chart of the dashboard `Marketplace` through the REST API | `Cancellations: 601 rows`, `Daily sales: 601 rows`, `Delivery SLA by state: 27 rows`, `GMV by category, top 10: 10 rows`, exit code 0 |
| Trino user `superset` (after the Trino restart, 15:02 UTC) | the rules of `grafana` (`docker/trino/etc/rules.json`, `grafana\|superset`): `select count(*) from lake_ro.gold.fct_orders` 96346; `lake_ro.silver.orders`, catalog `lake`, `lake_ro.gold.stg_orders` and `create table lake_ro.gold.x` get `Access Denied`; `grafana` and `dbt` read as before. The database is imported with `allow_dml: false` |
| `superset-mcp` with `FASTMCP_HTTP_HOST_ORIGIN_PROTECTION` (15:52 UTC) | `POST /mcp initialize`: `Host: evil.example:5008` 421, `Origin: http://evil.example` 403, loopback 200; every tool runs as `admin` (`MCP_DEV_USERNAME`), so a deployment beyond loopback needs a JWT provider |
| MCP client session | server `Superset MCP Server 3.4.11`; `tools/list`: `get_instance_info`, `health_check`, `search_tools`, `call_tool`; `tools/call get_instance_info`: 1 dashboard, 4 charts, 4 datasets, 1 database (trino); `claude mcp list` (client registered with `--scope local`, no client settings in the repository): `superset ... Connected` |
| Rerun of `superset-init` on an initialized metadata database (15:51 UTC) | `admin exists`, exit 0; then `check.py` as above. By the import flags (the comment above `superset-mcp` in `docker/compose.yaml`) the database, datasets and charts are kept (`overwrite=False`) and the dashboard `Marketplace` is replaced |
| `GET http://127.0.0.1:8088/health` | 200 |

Other web entries checked by `GET` on 2026-11-06: the MinIO console on `http://127.0.0.1:9001` answers
200 (port 9000 redirects there from a browser), the Lakekeeper UI on `http://127.0.0.1:8181/ui/`
answers 200. Kafka from the host (15:01 UTC): a `confluent-kafka` admin client with bootstrap
`127.0.0.1:9092` lists broker `1: localhost:9092` and the seven `oltp.shop.*` topics; the broker
advertises `localhost:9092` (`docker/compose.yaml:76`); before the fix it advertised
`localhost:29092`, which nothing listened on. Not proven: `bi` together with the other profiles under
the 16 GB limit (on 2026-11-06 it ran beside core, query, orchestrate, obs and stateful, but the
peak was not measured).

### Superset dashboard v2

The dashboard `Marketplace` in Superset has 13 charts in the Harbor palette (bundle in
[`docker/superset/dashboards`](../docker/superset/dashboards), notes in
[OPERATIONS, Superset](../OPERATIONS.md#superset-profile-bi)). KPI tiles of 2026-11-12, read through
`/api/v1/chart/data` with `SUPERSET_DATA_ANCHOR=2026-07-01`, "Last quarter" against the previous
quarter:

| KPI | Last quarter | Previous quarter |
|---|---|---|
| GMV | 2 687 103.87 | 2 863 849.49 |
| Orders | 18 991 | 21 355 |
| On-time delivery | 96.6% | 87.5% |

`docker exec lakehouse-superset-1 python /app/check.py` on 2026-11-13: all 13 charts return rows.
The tile "Data through" shows 18 Jul 2026. Screenshot: `planned`.

## Not proven yet

- `rewrite-position-deletes silver.orders` did not run live; the scheduled run skipped it.
- `iceberg_orphans` stays paused; running it weekly is the owner's decision.
- Scenario 8 live against `CdcStalledSourceWrites` (it is shorter than the alert window) and
  `SparkRestartLoop` as a live firing.
- The offline start of Grafana with a new `grafana` volume (the plugin install is synchronous).
- The 24 hour unattended window: not run, cancelled by the owner on 2026-11-04.
- Live loss of the silver checkpoint: covered by a Spark unit test only. A live run with an empty
  checkpoint on the live tables would rewrite about 506 thousand rows without an LSN (owner
  decision, 2026-11-04).
- A live schema change (migration 003, `sales_channel`): the owner's Modify gate, not done.
- The learning gates in [LEARNING.md](../LEARNING.md): `planned`.
- Trino authentication: not done. Access control (W6-T11) limits the `grafana` user, but the user
  name is only a label ([OPERATIONS, Access control](../OPERATIONS.md#access-control)).

## How it was built

The project is built by AI agents working for one engineer. The agents wrote the code, the tests
and the documentation; the owner decided the architecture, approved every risky action and
accepted the results. This section lists the artifacts that show it, and counts only what the
artifacts contain. The rules are in [AGENTS.md](../AGENTS.md) and
[docs/planning/13-harness.md](planning/13-harness.md) (sections 1 to 6; written in Russian, like
all of `docs/planning/`).

**Roles.** One orchestrator session (Opus) plus five roles in
[`.claude/agents/`](../.claude/agents): `Explore` (search), `scout` (analysis and read-only
probes), `implementer` (code), `reviewer` (independent review in a fresh context), `docs-writer`
(these documents). A task is a card in a spec with a "done when" line and a recorded result
("Итог") naming who did what and the reviewer verdict.

**Decisions.** Every decision of the closing block is a row in
[the W6 spec](planning/14-closeout-spec.md), section 2, with a group: 17 decisions, 4 taken by the
agent alone (group A), 5 by the agent after a `reviewer` verdict (group B), 8 by the owner
(group C: pushes and delegation, replay budget, live changes, access rights, and whether these
documents say how the project was built). The architecture
decisions behind the code are ADR-001 to ADR-026 in [DECISIONS.md](../DECISIONS.md); code is not
written against an ADR, a new ADR comes first.

**Owner approvals.** Actions with a blast radius (live deletes, replay spending, pushes, changes to
the source or the connector) stop until the owner says yes; a hook enforces part of it
(`.claude/hooks/guard.py`), including a refusal to commit without a full `make verify`, `make check`
and a `reviewer` verdict on the same tree. The approvals are logged in [HANDOFF](HANDOFF.md),
"Журнал «ок»": 28 entries dated 2026-10-27 to 2026-10-29 (`git show 46f5282:docs/HANDOFF.md | grep
-c '^| 2[789]\.10'` prints 28). The same period holds 14 commits (`git log --oneline 8964292..HEAD |
wc -l` at HEAD `46f5282`). The two numbers count different things: one approval can cover a live
step, a decision or a push, not only a commit. No commit message carries an attribution line (`git
log` has none).

**What review found.** Review by a separate agent in a fresh context returned work before it was
accepted. Examples, each with its record in [the W6 spec](planning/14-closeout-spec.md):

- Dashboard (W6-T01), round 0 "return", 1 high: order counts doubled when summed over states
  (96 650 against 96 163 real orders). Fixed by taking orders from `fct_orders`; see
  [Dashboard](#dashboard).
- `dq_checks` while CDC stands (W6-T07), round 0 "return", 2 high: the first version switched the
  value reconciliation off on any source write, which weakened the check, and the DAG wiring had no
  tests. The detector was redesigned to look at the replication slot, a difference at rest stays red
  when the source is silent, and 25 mutations of the new code were killed by the tests. Live proof:
  scenario 6 on 2026-10-29, above.
- First live maintenance (W5-T05b), plan review round 0 "return", 1 high: the rows of the JDBC
  catalog point to snapshots from before the catalog switch of 2026-10-08, and expire and orphan
  removal delete those files, so the rollback point would have been lost silently. Result: decision
  W6-D16 and a copy of `warehouse/` as the first step of the procedure.
- Harness (v0.3), round 0 "return", 1 high: a late "return" verdict without a tree id left an
  earlier "accept" valid. Accepted and fixed in round 1 ([HANDOFF](HANDOFF.md), 2026-10-29).
- Not found by review: the fixed-clock test that broke CI (see [CI and smoke](#ci-and-smoke)).
  It was caught by the pipeline after the push.

**Limits of the process.** `implementer` and `reviewer` hit their 60 turn limit on a long task
(about 22 and 29 minutes); the limit was raised to 100 and the owner asked the orchestrator to
finish the first fix round itself ([HANDOFF](HANDOFF.md), "harness v0.3"). The approval log is
kept by the agents with the owner's answer quoted or paraphrased, and it is not a signed record;
the entries of 2026-10-23 and 2026-10-24 were written after the fact and say so.

**These documents.** README, ARCHITECTURE, this page and the interview notes were drafted by the
`docs-writer` role from the cards' recorded results, with the source next to each number. A
fresh-context agent checks the result before it is accepted (`AGENTS.md`).
