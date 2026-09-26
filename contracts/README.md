# contracts

Schemas that code depends on. Changing one is a contract change: record it in `DECISIONS.md`.

- `cdc-envelope.schema.json`: shape of a Debezium event as bronze expects it. Validated in
  `tests/unit/test_envelope.py` against fixtures shaped after records from the live topics.
- `silver/<table>.json`: one JSON Schema per `shop` table, describing the row image in
  `before`/`after` and the silver column it becomes. `silver_upsert` parses the payload with
  these and `tests/unit/test_contracts.py` keeps them in step with `oltp/migrations`.

## Silver contract format

```
"x-source-table": "shop.orders",        source table; the file stem is the silver table
"x-primary-key": ["order_id"],          merge key, in Kafka key order; must be required
"required": [...],                      the NOT NULL columns of the source
"properties": {
  "order_purchase_timestamp": {"type": "integer", "x-silver-type": "timestamp_ntz"}
}
```

`type` is the JSON type on the wire, `x-silver-type` the Spark SQL type of the silver column.
The pairs in use follow from the connector settings (`connect/shop-connector.json`):

| Source | Wire | Silver | Why |
|---|---|---|---|
| `varchar`, `char`, `text` | `string` | `string` | |
| `integer`, `smallint` | `integer` | `int` | Iceberg has no smallint |
| `numeric(p, s)` | `number` | `decimal(p,s)` | `decimal.handling.mode=double` |
| `timestamp` | `integer` | `timestamp_ntz` | `time.precision.mode=connect`: epoch milliseconds of the naive source value, so microseconds are dropped; no time zone is invented |

Silver parses with the wire types and casts afterwards. A field that is present in the payload
but fails to parse or does not fit its silver type (a number out of range, a timestamp outside
year 1-9999) sends the event to `silver.quarantine` as `type_mismatch`; a field that is absent or
JSON null stays null, and a null in a required column is `null_required`.

Adding a column: add the property here, run `ALTER TABLE lake.silver.<table> ADD COLUMN`, and
new events fill it while older rows stay null. Bronze needs nothing, `after` is text. A column
that the source has and the contract does not yet know is ignored, not an error.
