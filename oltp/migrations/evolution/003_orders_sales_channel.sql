-- Schema evolution scenario (W2-T07). `make migrate` does not see this directory: the replayer
-- applies the file when its virtual clock reaches REPLAY_SCHEMA_EVOLUTION_AT, so the change
-- lands in the middle of the stream. Nullable with no default: orders written before stay null.
alter table shop.orders add column sales_channel varchar(16);

alter table shop.orders add constraint orders_sales_channel_check
check (sales_channel in ('web', 'app', 'marketplace'));
