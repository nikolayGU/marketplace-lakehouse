# connect

Debezium PostgreSQL connector for schema `shop`.

- `shop-connector.json`: connector config; `${VAR}` placeholders are substituted from `.env`
  by `register.sh` (week 1, W1-T05) before POSTing to `http://127.0.0.1:8083/connectors`.
- Topics `oltp.shop.<table>` are created explicitly with 3 partitions and 24 h retention
  before the connector starts (`KAFKA_AUTO_CREATE_TOPICS_ENABLE=false`).
- `tombstones.on.delete=false`: deletes arrive as `op = "d"` envelopes with `before`; silver
  turns them into soft deletes.
- Flattening (`ExtractNewRecordState`) is intentionally not used: bronze stores the full
  envelope (`before`, `after`, `op`, `ts_ms`, `source.lsn`), which is what makes late-event
  ordering and DELETE handling explainable.
