# observability

Configuration of profile `obs` (OPERATIONS.md, Observability). Compose mounts every file here
read-only; each must exist before the first `make up PROFILE=obs`.

- `prometheus/prometheus.yml`: scrape jobs `prometheus`, `spark-bronze` (`:4041`),
  `spark-orders-per-minute` (down by design unless profile `stateful` runs), `kafka-connect`
  (JMX exporter, `:9404`), `kafka-exporter`, `postgres-exporter`, `statsd-exporter`,
  `container-exporter`. Trino, Lakekeeper and the replayer are not scraped.
- `prometheus/alerts.yml`: group `lakehouse`, 13 alerts in 16 rules (`make alerts-test`:
  `SUCCESS: 16 rules found`); `prometheus/alerts_test.yml` holds the promtool tests. The table is
  in OPERATIONS.md, "Alerts".
- `postgres-exporter/queries.yaml`: `lakehouse_slot_retained_bytes` and `lakehouse_slot_active`.
- `statsd/mapping.yml`: StatsD names to Prometheus labels, Airflow and `dq_checks`.
  `lakehouse.*` and `lakehouse.dq.*` are mapped with a 45-minute TTL (`statsd/mapping.yml`).
- `grafana/provisioning`: Prometheus datasource (`uid: prometheus`), the Trino datasource for the
  business dashboard and a file provider for `grafana/dashboards` (`marketplace.json`,
  `pipeline-health.json`, `infra.json`). `alerting` and `plugins` are empty on purpose.
- `container-exporter/`: per-container metrics from the Docker API, in place of cAdvisor
  (ADR-023).

## Series

`dq_checks` sends DogStatsD gauges over UDP to `statsd-exporter:9125` (`lakehouse/metrics.py`,
`STATSD_HOST` and `STATSD_PORT` default to that); tags become labels, and the mapping gives every
`lakehouse.*` series a TTL of 45 minutes (three cadences), so a series disappears when `dq_checks`
stops instead of showing its last value for ever.

| Series | Labels | Meaning |
|---|---|---|
| `lakehouse_table_freshness_seconds` | `layer` (`silver`, `bronze`), `table` | seconds since the newest `_updated_at` (silver, 7 tables) or `ingest_ts` (bronze, per `source_table`); grows for hours between replay bursts, which is "no traffic", not a fault |
| `lakehouse_silver_lag_seconds` | none | seconds the oldest bronze snapshot silver has not merged has waited; 0 at rest. It is not freshness. Not sent while the Variable `silver_upsert_last_bronze_snapshot` is missing or names a snapshot bronze no longer has |
| `lakehouse_dq_silver_duplicate_keys` | `table` | primary keys twice in a silver table (8 incl. quarantine) |
| `lakehouse_dq_reconcile_tables_differing` | `at_rest` | tables whose live row count differs from Postgres |
| `lakehouse_dq_lsn_repeats_last_hour`, `lakehouse_dq_noop_updates_last_hour` | none | delivery repeats and no-op updates of the last hour |
| `lakehouse_dq_dbt_source_freshness_exit_code` | none | 0, or 1 for a stale source or a failed freshness query (the task then fails) |
| `lakehouse_dq_last_run_timestamp_seconds` | none | Unix time of the last `report` task |

`reconcile_values` adds the series of the value reconciliation:

| Series | Labels | Meaning |
|---|---|---|
| `lakehouse_dq_reconcile_rows` | `layer` (`source`, `silver`, `gold`), `table` | rows compared (20 series: 7 + 7 + 6; for `mart_daily_sales_gmv` the count is days) |
| `lakehouse_dq_reconcile_values_differing` | `pair` (`source_silver`, `silver_gold`, `source_gold`), `table` | keys on both sides whose row fingerprints differ (for `source_gold`: purchase dates whose GMV differs) |
| `lakehouse_dq_reconcile_keys_missing` | `pair`, `table`, `side` | keys the other side lacks; `side="right"` is a key the source (or silver) has and silver (or gold) lacks |
| `lakehouse_dq_reconcile_in_flight` | none | 1 while work is in flight and no verdict was made, while a stalled CDC keeps the source-silver pairs out (the silver-gold pairs are still compared), or when the CDC position moved during the run (the source-silver verdicts are dropped) |
| `lakehouse_dq_cdc_stalled` | none | 1 while CDC stands: the source wrote since the previous run (write counter of schema `shop` in `pg_stat_user_tables`) and `confirmed_flush_lsn` of `shop_slot` did not move; it stays 1 until the slot moves. 0 without a slot, and for one run after a reset of the statistics (1 again at the next write while the slot stands). Sent every run, whether or not counts differ |
| `lakehouse_dq_reconcile_verdict_timestamp_seconds` | none | Unix time of the last verdict |
| `lakehouse_dq_reconcile_gold_compared` | none | 1 when the run compared silver and gold, 0 when it did not: nothing at rest, or gold behind silver |
| `lakehouse_dq_reconcile_gmv_compared` | none | 1 when the run compared GMV per day with Postgres, 0 when it did not: not at rest, CDC stalled or moved during the run, gold behind silver, the mart behind `fct_orders`, or a failed GMV step |
| `lakehouse_dq_gold_not_compared_runs` | none | runs in a row without a silver-gold comparison (Airflow Variable `dq_gold_not_compared_runs`), 0 after a comparison |
| `lakehouse_dq_gold_stale_runs` | none | runs in a row that found the stand at rest and gold stale (Airflow Variable `dq_gold_stale_runs`), 0 after a run that did not; not sent when the check itself failed. Stale means: the newest data snapshot (operation other than `replace`) of the seven silver tables is newer than the oldest of the latest rebuilds of the seven table marts of gold (`dim_*`, `fct_order_items`, `fct_orders`, `mart_delivery_sla`, `mart_seller_performance`), or the watermark of `mart_daily_sales` is behind `fct_orders` (`airflow/dags/lakehouse/reconcile.py:170-212`, `SILVER_DATA_CHANGED`, `GOLD_REBUILT`, `MART_UPDATED`) |

## Dashboard check

`uv run python scripts/obs/check_dashboards.py` runs every panel query and lists the empty ones.
A Spark panel whose query ran fine but is empty is printed as `idle:` (exit 0) only if all of these
hold: the expression names exactly one `query="..."` and has no `on`, `ignoring` or `group_*`; that
query has no `spark_streaming_batch_duration_seconds` series (no batch with data since the start;
the listener sets it on every progress event); it reported progress or idle within 300 s
(`spark_streaming_last_batch_timestamp`); and every metric name, type (a counter with `_total`) and
selector of the panel has metadata or a series within the 7 days of Prometheus retention
(`--storage.tsdb.retention.time=7d` in `docker/compose.yaml`). Anything else, a typo included, is
`empty` and exit 1. After 7 days without a batch with data, or on a fresh Prometheus volume, these
panels are `empty` and the check exits 1 until the next batch with data; confirm with the "Seconds
since the last bronze batch" panel and `group(last_over_time(<selector>[7d]))`. Grafana shows "no
samples: no batch with data since start, or the job is down" on those panels.

## Notes

- Their `depends_on` on `core` services is `required: false`, so `make up PROFILE=obs` stays a
  valid project without `core`. The healthchecks of `kafka-exporter` and `postgres-exporter` look
  for `kafka_brokers` above 0 and `pg_up 1`, since `/metrics` answers 200 with the broker or the
  database down; without `core` both should stay unhealthy (not run live: `core` was up).
- `observability/prometheus` is mounted read-only as a directory. After editing rules or scrape
  configs: `docker exec lakehouse-prometheus-1 kill -HUP 1` (busybox `kill` is in the image).
  Never `docker kill -s HUP`: the daemon records any `docker kill` as a manual stop, and after the
  next Docker restart `unless-stopped` leaves the container down. That is the likely cause of
  Prometheus staying `Exited (255)` after the Docker restarts of 2026-10-27 and 2026-10-30, both
  after a `docker kill -s HUP` (inferred from moby's `killWithSignal`, not reproduced).
  `make report` lists such containers.
- Kafka Connect: `/kafka/config` is an anonymous volume of the Debezium image, and a recreated
  container keeps the old one. A file the image layer adds there is hidden, so `metrics.yaml` is
  bind-mounted; without it the agent stops the JVM and Connect restarts in a loop (2026-10-19,
  ten minutes of no CDC).
- Airflow sends StatsD over UDP: without `obs` the packets are lost and Airflow keeps running
  (scheduler healthy in 66 s with `obs` down, no `gaierror`, 2026-10-19). `dq_checks` tasks print
  `statsd: could not send` and stay green.
- Grafana provisioning is mounted whole over the image's directory, so `provisioning/alerting`
  and `provisioning/plugins` exist in the repo empty: without them Grafana logs errors.
- Every file compose mounts must exist before the first start: a missing file becomes a
  root-owned directory on the host. `find observability -type d -name '*.y*ml'` must print nothing.
- `container-exporter` holds the Docker socket (root on the host in effect) and only sends GET.
  It joins the socket's group `DOCKER_GID` from `.env`, as the scheduler does. A wrong group and an
  empty container list (`COMPOSE_PROJECT_NAME`) are in
  [ScrapeTargetDown](../docs/runbooks/containers.md#scrapetargetdown).
