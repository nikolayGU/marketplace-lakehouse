# Airflow DAG run failed (AirflowDagFailed)

Symptom: alert `AirflowDagFailed` (warn): `airflow_dagrun_failed_seconds_count` of a `dag_id`
grew in the last 30 minutes, so the alert has the label `dag_id` and keeps firing until the failed
run is 30 minutes old. It reads the counter that statsd-exporter keeps per DAG. A run that ends
`success` after a task retry never fires it. Known gap: the first failure in the 30 minutes after
Prometheus starts (and after a host sleep) is not caught; it is visible in Airflow and on the
"Failed Airflow DAG runs" panel of Pipeline health.

1. Which DAG and when: the `dag_id` label in `curl -s 127.0.0.1:9090/api/v1/alerts`, then
   `airflow dags list-runs <dag_id>` in the scheduler container (or the Airflow UI,
   `http://127.0.0.1:8090`). Open the red task and read its log.
2. Host sleep first. Sleep pauses the Docker VM, and a task in flight fails on wake. Look for
   `Heartbeat recovered after <n> seconds` just before the failure:
   `docker compose --env-file .env -f docker/compose.yaml logs --tail=2000 airflow-scheduler | grep 'Heartbeat recovered'`.
   Found: it is not a pipeline fault. Trigger the DAG again (`airflow dags trigger <dag_id>`).
   Why it fails and the Windows setting that stops it: `../../OPERATIONS.md#airflow`.
3. `silver_upsert`: the `merge` task log has the Spark error. `409` or
   `name "/lakehouse-silver-merge" is already in use`: a second writer, or a container left after a
   killed scheduler. `docker ps -a --filter 'name=^/lakehouse-silver-merge$' --format '{{.Status}}'`:
   `Up` is a live writer, wait for it; `Exited` is a leftover, and `docker rm` is for the owner to
   approve, never `rm -f` on an `Up` one. `Process timed out` followed by `NotFound: No such
   container` is a task timeout, not a second error. Details: "Timeouts" in
   `../../OPERATIONS.md#airflow`. The task retries once after one minute; a run that recovers
   by the retry does not fire this alert (it shows as `try_number` 2).
4. `dbt_build`: the task log names the failing test (`Failure in test <name>`). `dbt build` skips
   the children of a failed test, and the marts keep their previous snapshot. Remove the cause,
   then `airflow dags trigger dbt_build`; the task has no retries.
5. `dq_checks`: a red task is a verdict or a failed query, not a Prometheus problem. Go to
   `dq-checks.md`; how to read each red task is in `../../OPERATIONS.md#airflow`.
6. `iceberg_maintenance`, `iceberg_orphans`: read the task log; these DAGs use the pools
   `lake_writers` (shared with `silver_upsert`) and `gold_writers` (shared with `dbt_build`). Do not run `expire_snapshots`,
   `remove_orphan_files` or a non-dry run by hand to fix a red task: both are on the blast-radius
   list and need the owner's approval (OPERATIONS.md, "Maintenance").

Reproduce: `make chaos-break-dbt-test` (OPERATIONS.md, scenario 9): the alert fired 17 s after the
red run ended.
