# oltp

Source system: PostgreSQL schema `shop` and the replayer that feeds it.

- `init/`: entrypoint SQL run once by the container: `debezium` role with REPLICATION, publication
  `shop_publication`, schema `shop`.
- `migrations/`: numbered SQL migrations applied by the replayer on start (`001_schema.sql`,
  `002_orders_sales_channel.sql` for the schema-evolution scenario).
- `replayer/`: Python package. `load` bulk-loads Olist with shifted dates; `start` replays the
  remaining history on a virtual clock; `status` prints position. State lives in
  `shop.replay_state`, so restarts continue instead of reloading.

Tables: customers, sellers, products, orders, order_items, payments, reviews.
Knobs: `REPLAY_SPEED`, `REPLAY_INITIAL_SHARE`, `REPLAY_LATE_RATIO`, `REPLAY_LATE_DELAY_SECONDS`,
`REPLAY_DUPLICATE_RATIO`, `REPLAY_SCHEMA_EVOLUTION_AT`.
