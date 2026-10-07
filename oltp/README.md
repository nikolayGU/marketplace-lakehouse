# oltp

Source system: PostgreSQL schema `shop` and the replayer that feeds it.

- `init/`: `01-debezium.sh`, run once by the container on an empty data directory: schema `shop`,
  the `debezium` role with REPLICATION, and publication `shop_publication`. The publication is
  declared `for tables in schema shop`, so migrations can add tables without touching it.
- `migrations/`: numbered SQL migrations (`001_schema.sql`, `002_debezium_signal.sql` for
  ADR-019). Applied by `make migrate`, tracked in `public.schema_migrations`, which sits outside
  `shop` so it never reaches CDC. `migrations/evolution/` is not part of that set, see below.
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

Schema evolution (W2-T07): `migrations/evolution/003_orders_sales_channel.sql` adds a nullable
`shop.orders.sales_channel` (`web`, `app` or `marketplace`) in the middle of the stream.
`make migrate` reads only `migrations/*.sql` and never sees it. `start` applies it once its
virtual clock reaches `REPLAY_SCHEMA_EVOLUTION_AT`: an ISO timestamp without a zone, in the same
shifted virtual time as `virtual_now` from `status` (`2026-07-01T12:00:00`). Empty means never;
a mark already behind the clock fires on the first step. The file goes through the same
`migrations.apply`, so it lands in `public.schema_migrations`, but the replayer decides whether it
is due by the column itself: `sales_channel` present in `shop.orders` means applied. That holds
across restarts and also when someone added the column by hand, where a second `ALTER` would fail.
From then on new orders get a channel picked by `md5(order_id)`, so a rerun picks the same one,
and orders written before stay null. The moment is counted in
`replayer_events_total{kind="schema_evolution"}`.

Older clones: the value is now parsed strictly, and the old `.env.example` line
`REPLAY_SCHEMA_EVOLUTION_AT=  # ...` reads as the comment text itself (in python-dotenv and in
Compose), so every replayer command, `make migrate` included, fails with a `ValidationError`;
`make secrets` keeps an existing `.env`, so clear the line by hand:
`sed -i 's/^REPLAY_SCHEMA_EVOLUTION_AT=[[:space:]]*#.*/REPLAY_SCHEMA_EVOLUTION_AT=/' .env`.

Tables: customers, sellers, products, orders, order_items, payments, reviews.
Knobs: `REPLAY_SPEED`, `REPLAY_INITIAL_SHARE`, `REPLAY_LATE_RATIO`, `REPLAY_LATE_DELAY_SECONDS`,
`REPLAY_DUPLICATE_RATIO`, `REPLAY_SCHEMA_EVOLUTION_AT`.
