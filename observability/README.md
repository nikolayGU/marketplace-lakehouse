# observability

Configuration of profile `obs` (OPERATIONS.md, Observability). Compose mounts every file here
read-only; each must exist before the first `make up PROFILE=obs`.

- `prometheus/prometheus.yml`: scrape jobs `prometheus`, `spark-bronze` (`:4041`),
  `kafka-exporter`, `postgres-exporter`, `statsd-exporter`, `container-exporter`. Kafka Connect
  (JMX) lands with W4-T01b. Trino, Lakekeeper and the replayer are not scraped.
- `prometheus/alerts.yml`: group `lakehouse`, rules land with W4-T05.
- `postgres-exporter/queries.yaml`: `lakehouse_slot_retained_bytes` and `lakehouse_slot_active`.
- `statsd/mapping.yml`: StatsD names to Prometheus labels, Airflow (W4-T01b) and `dq_checks`
  (W4-T03).
- `grafana/provisioning`: Prometheus datasource (`uid: prometheus`) and a file provider for
  `grafana/dashboards` (W4-T04). `alerting` and `plugins` are empty on purpose.
- `container-exporter/`: per-container metrics from the Docker API, in place of cAdvisor
  (ADR-023).
