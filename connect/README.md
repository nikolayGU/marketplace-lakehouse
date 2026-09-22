# connect

Debezium PostgreSQL connector for schema `shop`.

- `shop-connector.json`: connector config; `${VAR}` placeholders are substituted from `.env`
  by `register.sh` (week 1, W1-T05) before POSTing to `http://127.0.0.1:8083/connectors`.
- Topics `oltp.shop.<table>` are created explicitly with 3 partitions and 24 h retention
  before the connector starts (`KAFKA_AUTO_CREATE_TOPICS_ENABLE=false`).
- `tombstones.on.delete=false`: deletes arrive as `op = "d"` envelopes with `before`; silver
  turns them into soft deletes.
- `signal.data.collection=cdc.debezium_signal` (ADR-019): `make cdc-snapshot [TABLES=...]`
  inserts an `execute-snapshot` row and the connector re-reads those tables as `op = "r"`
  events while streaming goes on. The signal table is published to `oltp.cdc.debezium_signal`,
  which `register.sh` creates; bronze's `oltp\.shop\..*` pattern leaves it out.
- Flattening (`ExtractNewRecordState`) is intentionally not used: bronze stores the full
  envelope (`before`, `after`, `op`, `ts_ms`, `source.lsn`), which is what makes late-event
  ordering and DELETE handling explainable.
