# dq_checks did not run, compare or see a rebuild (DqChecksStale, SilverGoldNotCompared, GoldStaleAtRest)

`dq_checks` runs every 15 minutes and sends every `lakehouse_dq_*` gauge, so alerts on them lag by
up to that much. A red `dq_checks` task is a different thing (a verdict, not a stopped DAG): see
`../../OPERATIONS.md#airflow`. A red run also fires `AirflowDagFailed` (`airflow-dag-failed.md`).

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
raise a false one (OPERATIONS.md, "Alerts").

Reproduce: not run live: covered by promtool (`make alerts-test`); the lost Asset event itself
happened in scenario 10b.
