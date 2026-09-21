# oltp

Source system: PostgreSQL schema `shop` and the replayer that feeds it.

- `init/`: `01-debezium.sh`, run once by the container on an empty data directory: schema `shop`,
  the `debezium` role with REPLICATION, and publication `shop_publication`. The publication is
  declared `for tables in schema shop`, so migrations can add tables without touching it.
- `migrations/`: numbered SQL migrations (`001_schema.sql`; `002_orders_sales_channel.sql` comes
  with the schema-evolution scenario). Applied by `make migrate`, tracked in
  `public.schema_migrations`, which sits outside `shop` so it never reaches CDC.
- `replayer/`: Python package. `migrations` applies the SQL above; `load` bulk-loads the CSVs
  with COPY into empty tables. `start` (virtual clock, shifted dates, `shop.replay_state`) and
  `status` arrive with W1-T04.

Tables: customers, sellers, products, orders, order_items, payments, reviews.
Knobs: `REPLAY_SPEED`, `REPLAY_INITIAL_SHARE`, `REPLAY_LATE_RATIO`, `REPLAY_LATE_DELAY_SECONDS`,
`REPLAY_DUPLICATE_RATIO`, `REPLAY_SCHEMA_EVOLUTION_AT`.
