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
- `statsd/mapping.yml`: StatsD names to Prometheus labels, Airflow and `dq_checks`. Names it does
  not map are exported with dots turned into underscores, which is how `lakehouse.dq.gold_stale_runs`
  becomes `lakehouse_dq_gold_stale_runs`, the series behind `GoldStaleAtRest`.
- `grafana/provisioning`: Prometheus datasource (`uid: prometheus`), the Trino datasource for the
  business dashboard and a file provider for `grafana/dashboards` (`marketplace.json`,
  `pipeline-health.json`, `infra.json`). `alerting` and `plugins` are empty on purpose.
- `container-exporter/`: per-container metrics from the Docker API, in place of cAdvisor
  (ADR-023).
