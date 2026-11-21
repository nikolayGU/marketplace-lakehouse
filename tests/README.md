# tests

Everything in `tests/unit/` runs under `uv run pytest tests/unit` (`make test`). Fixtures:
`fixtures/envelopes/` holds Debezium records shaped after the live topics, ids replaced.
About half of the tests check the commit-gate hooks and the stamp logic of the repository workflow
(`test_agent_hooks.py`, `test_agent_state.py`), not the data product.

## What lives where

| Area | Files | Where it runs | Catches | Does not catch |
|---|---|---|---|---|
| Commit-gate hooks | `test_agent_hooks`, `test_agent_state`, `test_agent_docs` | host, CI `lint-and-test` | hook decisions, stamps, gates | |
| CDC envelope, contracts | `test_envelope`, `test_contracts` | host; Spark part also `spark-tests` | contract against the migration, types, NOT NULL, primary keys | a narrowed `enum` |
| Bronze and stream metrics | `test_bronze_cdc_ingest`, `test_iceberg_sink`, `test_offsets`, `test_spark_settings`, `test_metrics_listener` | host in part; Iceberg part only `spark-tests` | epoch skip by query id, lag, catalog settings | a live Lakekeeper REST and MinIO |
| Silver MERGE | `test_silver_upsert` | JVM part on the host with Java 17; Iceberg part only `spark-tests` | LSN guard, replay of a batch, late rows, deletes, quarantine, lost checkpoint | |
| `orders_per_minute` | `test_orders_per_minute` | `spark-tests` | window, watermark | a live Kafka |
| Spark maintenance | `test_maintenance`, `test_iceberg_demo` | host, `spark-tests` | job rules, expire, orphans dry run | |
| Replayer | `test_replay_*`, `test_replayer_cli`, `test_load`, `test_progress`, `test_settings`, `test_sample`, `test_fetch_data` | host, CI | selection, virtual clock, schema evolution, CLI | the core `step()` against a real database |
| Reconcile | `test_reconcile`, `test_reconcile_sql`, `test_reconcile_shell`, `test_reconcile_postgres` | host; Postgres part in CI | the 7 tables, fingerprint, decimal sums, GMV statuses | the `_is_deleted` filter on the silver side of the value comparison |
| DAGs and data quality | `test_dags`, `test_dq_metrics`, `test_airflow_env` | host, CI; `make dags-check` in the Airflow image | gold gate, stale run counter, switch, timeouts | the wiring of `silver_upsert` against a live Airflow |
| verify, chaos, Makefile | `test_verify_script`, `test_chaos_silver_kill`, `test_chaos_lib`, `test_report`, `test_makefile`, `test_make_env` | host, CI | probes, signals, scenario 10b, `make silver` | the SQL semantics of the offsets check |
| dbt, static | `test_dbt_soft_delete`, `test_dbt_relationships`, `test_dbt_bi_columns`, `test_dbt_exposures` | host, CI | soft-delete filter, watermark, relationships | the models and dbt tests themselves (see below) |
| Superset | `test_superset_bundle`, `test_superset_import`, `test_superset_style` | host, CI | columns against dbt, category filter, theme, import order | KPI formulas |
| Grafana, exporter | `test_marketplace_dashboard`, `test_check_dashboards`, `test_container_exporter` | host, CI | only `lake_ro.gold`, no `double`, metric parsing | a hang without a deadline |
| Config and CI | `test_compose`, `test_pinning`, `test_minio_image`, `test_trino_access`, `test_workflows` | host, CI | digests, action SHAs, ports, Trino rules on its own evaluator | a dropped CI step or `SPARK_TESTS` file |
| Alerts | `observability/prometheus/alerts_test.yml` (promtool) | CI job `alerts-test`, `make alerts-test` | thresholds, `for`, absent | |

## Skips on a host

Three classes skip on a plain host and run in CI:

| Skip reason | Files | Where it runs |
|---|---|---|
| `RECONCILE_TEST_DSN is not set` | `test_reconcile_postgres.py` | a CI step against a Postgres service (`.github/workflows/ci.yml`), with `FAIL_ON_SKIP=1`. On a laptop the variable must never point at the Postgres of the stack: the tests create their own database |
| `local SparkSession needs Java 17 (Spark 3.5); CI and the image have it` | `test_silver_upsert`, `test_bronze_cdc_ingest`, `test_contracts`, `test_orders_per_minute` | `lint-and-test` on the runner's Java 17, and again in `spark-tests` |
| `needs the Iceberg runtime jar: run make test-spark` | `test_silver_upsert`, `test_maintenance`, `test_orders_per_minute`, `test_iceberg_*`, `test_bronze_cdc_ingest` | only `make test-spark` and the CI job `spark-tests` |

`make test-spark` runs the Spark tests in the Spark image (`SPARK_TESTS` in the Makefile lists the
files, `SPARK_IMAGE` picks the image, CI uses `lakehouse/spark:ci`). Inside the image a skip fails
the run, so the MERGE, quarantine and epoch tests cannot be skipped silently.

## Live stack only

CI runs `dbt parse` and the static SQL checks above. These are proven on a running stack, outside
pytest:

- `dbt build` with its dbt tests (`make dbt-build`, Trino);
- DAG runs in Airflow;
- the chaos scenarios (`make chaos-*`);
- the Superset and Grafana dashboards over live data.

`.github/workflows/smoke.yml` starts a clean clone (bootstrap, one minute of replay, `verify`, a
second bootstrap) and ends at silver: it does not run `dbt build`. Results and dates:
[docs/evidence.md](../docs/evidence.md).

`test_workflows.py` guards the workflows (every Dockerfile in the hadolint matrix, actions pinned
by commit SHA, no secrets but `GITHUB_TOKEN`, smoke triggers).
