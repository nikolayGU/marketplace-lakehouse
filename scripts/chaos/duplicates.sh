#!/usr/bin/env bash
# Chaos 3: the source repeats itself. REPLAY_DUPLICATE_RATIO picks that share of orders (md5 of
# duplicate:<order_id>) and runs each status UPDATE of a picked order twice with the same values:
# a new WAL record, a new LSN, before = after. Bronze gets an extra event that dedup by LSN cannot
# see. The repeat commits with its original, so silver usually reads both in one batch:
# latest_per_key keeps the repeat (higher LSN, same values) and MERGE writes the row once. If a
# batch boundary splits the pair, the _last_lsn guard lets the repeat rewrite the row with the
# same values. Either way silver ends equal to Postgres (OPERATIONS.md, scenario 3).
. "$(dirname "$0")/lib.sh"

ratio=0.1
no_other_replayer
# The window must hold only this burst: anything still on its way from Kafka would land in it.
wait_until 300 "bronze to catch up before the burst" bronze_caught_up
t0=$(date -u +'%Y-%m-%d %H:%M:%S')
echo "window: ingest_ts >= timestamp '$t0' (UTC), REPLAY_DUPLICATE_RATIO=$ratio"
replay_burst 120 REPLAY_DUPLICATE_RATIO=$ratio
wait_until 300 "bronze to catch up with Kafka" bronze_caught_up
echo "bronze caught up at $(date -u +%T)"

# The ratio picks orders, so pct_of_status_updates varies around it with the orders in the burst.
trino "select source_table, count(*) as events, count_if(op = 'u') as updates,
              count_if(op = 'u' and before = after) as no_op_updates,
              cast(100.0 * count_if(op = 'u' and before = after)
                   / nullif(count_if(op = 'u' and before <> after), 0) as decimal(5, 1))
                as pct_of_status_updates,
              count(distinct key) filter (where op = 'u') as keys_updated,
              count(distinct key) filter (where op = 'u' and before = after) as keys_repeated
       from bronze.cdc_events where ingest_ts >= timestamp '$t0' group by 1 order by 1"
lsn_duplicates_since "$t0"

no_ops=$(trino_value "select count_if(op = 'u' and before = after) from bronze.cdc_events
                      where source_table = 'orders' and ingest_ts >= timestamp '$t0'")
if ! [ "$no_ops" -gt 0 ]; then
  echo "FAIL: no no-op UPDATE on orders since $t0 UTC, the burst proved nothing" >&2
  exit 1
fi
repeats=$(trino_value "select count(*) from (select 1 from bronze.cdc_events
                         where ingest_ts >= timestamp '$t0' and lsn is not null
                         group by source_table, key, lsn having count(*) > 1)")
if [ "$repeats" != 0 ]; then
  echo "FAIL: $repeats changes arrived twice with the same LSN: a delivery repeat (chaos 2b)" \
    "mixed into the window" >&2
  exit 1
fi

echo "silver run at $(date -u +%T)"
run_silver
# Positive control: a repeat never changes a row count, so reconcile alone cannot show that silver
# read it. An order with a repeat ends on one, and silver must hold exactly that LSN and status.
counts=$(trino_value "
  with ev as (
    select json_extract_scalar(key, '\$.order_id') as order_id, lsn,
           op = 'u' and before = after as no_op,
           json_extract_scalar(after, '\$.order_status') as status,
           max(lsn) over (partition by key) as last_lsn
    from bronze.cdc_events
    where source_table = 'orders' and ingest_ts >= timestamp '$t0')
  select count(*), count_if(s._last_lsn = ev.lsn and s.order_status = ev.status)
  from ev left join silver.orders s on s.order_id = ev.order_id
  where ev.no_op and ev.lsn = ev.last_lsn")
read -r repeated held <<<"$counts"
echo "orders whose last event is a repeat: $repeated, silver holds that repeat: $held"
if ! [ "$repeated" -gt 0 ] || [ "$held" != "$repeated" ]; then
  echo "FAIL: silver holds the repeat of $held of $repeated orders that end on one" >&2
  exit 1
fi
reconcile || { echo "FAIL: reconcile, see the lines above" >&2; exit 1; }
echo "ok: $no_ops no-op UPDATEs on orders, none repeated by LSN; silver holds every repeat and" \
  "matches Postgres"
