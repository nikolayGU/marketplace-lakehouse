# oltp

Source system: PostgreSQL schema `shop` and the replayer that feeds it.

- `init/`: `01-debezium.sh`, run once by the container on an empty data directory: schema `shop`,
  the `debezium` role with REPLICATION, and publication `shop_publication`. The publication is
  declared `for tables in schema shop`, so migrations can add tables without touching it.
- `migrations/`: numbered SQL migrations (`001_schema.sql`; `002_orders_sales_channel.sql` comes
  with the schema-evolution scenario). Applied by `make migrate`, tracked in
  `public.schema_migrations`, which sits outside `shop` so it never reaches CDC.
- `replayer/`: Python package, `python -m replayer <command>`.

| Command | Does |
|---|---|
| `migrate` | applies `migrations/`, tracked in `public.schema_migrations` |
| `load` | shifts every timestamp onto today's calendar, bulk-loads the first `REPLAY_INITIAL_SHARE` of history into `shop`, stages the rest and materialises the event schedule |
| `start` | walks the schedule on the virtual clock, writing real INSERT, UPDATE and DELETE |
| `status` | prints the replay position |
| `reset` | destructive: empties `shop` and drops staging, needs `--yes` |

State lives in schema `replay`, not `shop`: the CDC publication covers `shop` wholesale, and
the replayer's own bookkeeping has no business in the change stream. `replay.schedule` holds one
row per thing that must happen, with `emitted_at` as the resume point, so a restart continues
instead of reloading. `replay.orders` and friends stage the history that has not played yet.

Each replayed order walks its real lifecycle: inserted as `created` with its items and payments,
then updated to `approved`, `shipped`, `delivered` at the source timestamps, then to whatever
status the dataset actually ends on. Cancelled-before-shipping orders have their items deleted,
and a thin deterministic slice of reviews is withdrawn, so silver sees genuine deletes.

Tables: customers, sellers, products, orders, order_items, payments, reviews.
Knobs: `REPLAY_SPEED`, `REPLAY_INITIAL_SHARE`, `REPLAY_LATE_RATIO`, `REPLAY_LATE_DELAY_SECONDS`,
`REPLAY_DUPLICATE_RATIO`, `REPLAY_SCHEMA_EVOLUTION_AT`.
