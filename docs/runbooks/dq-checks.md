# dq_checks did not run, compare or see a rebuild (DqChecksStale, SilverGoldNotCompared, GoldStaleAtRest)

`dq_checks` runs every 15 minutes and sends every `lakehouse_dq_*` gauge, so alerts on them lag by
up to that much. A red `dq_checks` task is a different thing (a verdict, not a stopped DAG): see
[A red dq_checks task](#a-red-dq_checks-task). A red run also fires `AirflowDagFailed` (`airflow-dag-failed.md`).

## DqChecksStale

Symptom: alert `DqChecksStale` (warn). `cause="stale"`: the last
`lakehouse_dq_last_run_timestamp_seconds` is older than 30 minutes. `cause="gone"`: the series is
absent for 15 minutes. The stamp is sent by the last task `report`, so a failing `report` stops
it even when the other tasks are green.

1. Is `dq_checks` unpaused and is the scheduler up? In Airflow (`http://127.0.0.1:8090`) or
   `docker compose ps airflow-scheduler`. A paused DAG or a stopped scheduler is the usual cause.
2. `airflow dags list-runs dq_checks`. A run in flight when the host slept fails on wake:
   `airflow-dag-failed.md`, step 2.
3. `report` red: its log has the query that failed. The task only reads Trino, so check `trino`
   and `minio` with `make status`.
4. Not a fault: a `dq_checks` paused on purpose (a chaos script pauses it). Unpause it when that work is
   done.

Reproduce: pause `dq_checks` and wait 30 minutes. Not run live: covered by promtool
(`make alerts-test`).

## SilverGoldNotCompared

Symptom: alert `SilverGoldNotCompared` (warn): `lakehouse_dq_gold_not_compared_runs` is 24 or more,
that is 24 runs in a row (6 hours of `dq_checks` working) that did not compare silver with gold.
Host sleep does not count and does not reset it. A dead `dq_checks` is `DqChecksStale`, not this.

1. Is a replay running without a pause? `make replay-status`. Silver and gold are compared only at
   rest, and a continuous replay never rests: the log says `in flight: bronze or silver
   has not caught up yet, no verdict`. This is the
   expected result of a continuous 24 hour run. Replay in bursts rests between them and resets the
   count.
2. At rest, but the log says `gold has not caught up with silver: the silver-gold pairs wait for
   dbt_build`: gold was not rebuilt. Same cause as `GoldStaleAtRest` below: is `dbt_build`
   unpaused and green (`airflow dags list-runs dbt_build`)?
3. The count is also in the log: `dq gold_not_compared_runs=<n>`. It falls to 0 at the first run
   that compares.

Reproduce: not run live: covered by promtool (`make alerts-test`).

## GoldStaleAtRest

Symptom: alert `GoldStaleAtRest` (warn): `lakehouse_dq_gold_stale_runs` is 2 or more, so two runs
in a row (30 minutes) found nothing in flight and a gold table older than the last data commit of
silver (by Iceberg snapshots), or the incremental mart behind `fct_orders`. One run can be the
build on its way: `dbt_build` takes under a minute.

1. `dbt_build` paused or red: `airflow dags list-runs dbt_build`. Red: `airflow-dag-failed.md`,
   step 4.
2. A paused `dbt_build` loses the Asset event `lake.silver` and does not replay it on unpause.
   Trigger it once by hand: `airflow dags trigger dbt_build`. Why:
   OPERATIONS.md, "Airflow" (the 2026-11-06 run).
3. Silent under continuous load (a known limit): while a replay runs without rest, a forgotten
   pause of `dbt_build` does not fire this alert. After 6 hours the signal is
   `SilverGoldNotCompared`, above.
4. The count is in the log: `dq gold_stale_runs=<n>`. It falls to 0 once gold is rebuilt.

Limits: it compares commit times, not the snapshot dbt read; both only miss an alert, they do not
raise a false one (`../evidence.md#alerts-and-time-to-fire`).

Reproduce: not run live: covered by promtool (`make alerts-test`); the lost Asset event itself
happened in scenario 10b.

## A red dq_checks task

A red task is a verdict or a failed query, not a stopped DAG. It also fires `AirflowDagFailed`.
Open the red task's log and find it below.

What `reconcile_values` compares (`airflow/dags/dq_checks.py`, `reconcile_values`):

- A row fingerprint is the md5 of the canonical text of every column (null as `\N`, decimals at
  the contract scale, timestamps as epoch milliseconds), built the same in Postgres and Trino. A
  table is the row count plus the md5 of its sorted `key=fingerprint` pairs. `make reconcile` uses
  the same fingerprint for the source-silver pairs only and without the at-rest check.
- Pairs: each of the seven source tables against silver (live rows), and `fct_orders`,
  `fct_order_items` (soft-deleted rows included, with their flag), `dim_products`, `dim_sellers`
  against silver; `dim_customers` only by row count (its grain is `customer_unique_id`).
- Only at rest (`checks.at_rest`). Otherwise the task is green, prints `in flight, no verdict` and
  sets `lakehouse_dq_reconcile_in_flight` to 1. With a stalled CDC only the silver-gold pairs run.
- The silver-gold pairs wait for the gold gate: no data commit of silver is newer than the last
  rebuild of gold, read from the Iceberg snapshots (`reconcile.gold_stale`), not from
  `fct_orders.updated_at`. Otherwise the log says `gold has not caught up with silver: the
  silver-gold pairs wait for dbt_build`.
- The CDC position (write counter of schema `shop`, confirmed LSN of the slot) is read before the
  source-silver pairs and again after them. If it moved, or the second read failed, the log says
  `in flight: the source or the slot moved during the run`, and the source-silver verdicts are
  dropped; a failed read also turns the task red (`dq cdc_reread_failed=1`, below).
- Red means a value differs at rest: the log lists the first 20 keys of each kind of difference
  and, for a key silver lacks, why (`quarantined`, `merge_pending`, `unknown`). Measured
  2026-10-23: 7 source-silver and 5 silver-gold verdicts in 7 s inside the task (25 s through the
  Trino CLI), 0 differing, 19 `reconcile_rows` series (before the GMV pair); right after a 20 s
  burst the task said `in flight`. The negative path (a changed value at an equal count, a missing
  key and its reason) is covered by unit tests, since a live difference would have to be written
  to the source, and from there it goes to silver.

What the GMV comparison does: after the silver-gold pairs, `reconcile_values` compares GMV per
purchase date in Postgres (`sum(price)` of `shop.order_items` joined to `shop.orders`, status not
`canceled` or `unavailable`, the filter of `int_daily_sales`) with `gold.mart_daily_sales` (days
with a live item), pair `source_gold`, table `mart_daily_sales_gmv`, exact decimal text.

- It runs only when the source pairs run (at rest, CDC not stalled, position not moved) and only
  when the mart has caught up with `fct_orders` (`max(source_updated_at)` of the mart not older
  than `max(updated_at)` of `fct_orders`), since `dbt build` rebuilds `fct_orders` before the mart.
  Otherwise the log says `mart_daily_sales has not caught up with fct_orders: GMV not compared`.
- Postgres is read last: the CDC position is read once more just before the GMV query. If it
  differs, the log says `in flight: ... GMV not compared`.
- The full recompute test compares the mart only with `int_daily_sales`, so a wrong filter in that
  model passes it; this comparison does not share the model's SQL.
- Measured 2026-10-30 by `select`: 596 days, fingerprint `0857d53200f24741049bbdf3c2d3520f` on
  both sides, totals 13 101 558.80 and 108 637 items. The same GMV computed with `canceled` left
  in gives another fingerprint (`ba89f32e...`), so such a change in the model turns the task red
  for every date dbt rebuilds after it.

How to read each red task:

1. `silver_keys_unique`: silver holds a primary key twice, which MERGE must never produce. Read
   the last `silver_upsert` log and the quarantine.
2. `silver_matches_postgres`: counts differ although bronze has been quiet for 5 minutes, silver
   merged its latest snapshot and CDC is not stalled, so a change never reached silver. `make
   verify` (with the scheduler stopped) shows the offsets and the counts. Differences with
   `at_rest=False` are normal during a replay burst and do not fail the task.
3. `reconcile_values`, a pair other than `source_gold`: a value or a key differs at rest. The log
   names the pair, the table and the first 20 keys with the reason.
4. `reconcile_values` with `source_gold mart_daily_sales_gmv`: GMV of a purchase date in the mart
   differs from Postgres at rest; the log names the dates. While neither `silver_upsert` nor
   `dbt_build` runs,
   `cd dbt && uv run dbt build --profiles-dir . --target dev --select mart_daily_sales --full-refresh`
   rebuilds the mart. A wrong filter in `int_daily_sales` needs a fix of the model. A seller moved
   to another state does not change GMV per day; only the full recompute test sees it.
5. `dq reconcile_gmv_failed=1` in the log: a failed GMV step (the `MART_UPDATED` read, the CDC
   read just before the GMV query or a GMV query), not a difference. Read the error next to it. The finished verdicts
   and the run count are still printed and sent, `lakehouse_dq_reconcile_gmv_compared` is 0, and
   the task then fails with that error. With a difference found at the same time it fails with
   `ValueError` that lists the difference and names the failure.
6. `dq cdc_reread_failed=1`: the CDC position could not be read again after the source-silver
   pairs. Their verdicts are dropped as in flight, the gauges are sent, and the task then fails
   with that error. Read the Postgres error next to it.
7. `dq gold_stale_failed=1`, two cases. The check of the Iceberg snapshots of gold failed: the
   gate stays closed, the silver-gold pairs are not compared, both run counts stay as they were,
   the verdicts are sent. The read of the mart watermark failed: the silver-gold pairs were
   compared if the gate was open and `gold_not_compared_runs` is updated, only `gold_stale_runs` stays as it
   was. Either way the task then fails with that error. Read the Trino error next to it (`trino`
   and `minio` in `make status`).
8. `dbt_source_freshness`: exit code 1 is a stale source and is logged, not failed: no traffic is
   not a broken pipeline. The task fails on another exit code (a signal such as an OOM kill gives
   a negative one) or when the freshness query itself failed for a source.
