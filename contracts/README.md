# contracts

Schemas that code depends on. Changing one is a contract change: record it in `DECISIONS.md`.

- `cdc-envelope.schema.json`: shape of a Debezium event as bronze expects it. Validated in
  `tests/unit/test_envelope.py`.
- `silver/<table>.json` (week 2): typed columns for each silver table, used by `silver_upsert`
  to parse `after` and by `ALTER TABLE` migrations. Adding a column here plus an Iceberg
  `ADD COLUMN` is the schema evolution path.
