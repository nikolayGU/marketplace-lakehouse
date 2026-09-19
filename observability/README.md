# observability

- `prometheus/prometheus.yml`: scrape kafka-exporter, postgres-exporter, kafka-connect (JMX),
  spark-bronze (`:4041/metrics`), oltp-replayer (`:8000/metrics`), statsd-exporter (Airflow),
  cadvisor, lakekeeper, trino.
- `prometheus/alerts.yml`: `ConnectorNotRunning`, `SlotWalRetainedHigh`, `SparkNoBatch5m`,
  `FreshnessAbove15m`, `AirflowDagFailed`, `ContainerRestarting`.
- `grafana/dashboards`: `pipeline-health.json`, `infra.json`, provisioned from files.
- `postgres-exporter/queries.yaml`: `pg_replication_slots` with retained WAL bytes.
- `statsd/mapping.yml`: Airflow StatsD metric names to Prometheus labels.
