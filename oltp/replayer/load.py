"""Shift the Olist history onto today's calendar, bulk-load the first share, stage the rest.

Reference data (customers, sellers, products) has no timestamps and goes straight into `shop`.
The four history tables land in `replay` staging, get shifted by one constant interval, and are
then split: everything at or before the cutoff is inserted as the initial load, the remainder
stays staged and becomes the schedule the replayer works through.
"""

import csv
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import psycopg

from replayer import state
from replayer.settings import Settings

REFERENCE: tuple[tuple[str, str], ...] = (
    ("customers", "olist_customers_dataset.csv"),
    ("sellers", "olist_sellers_dataset.csv"),
    ("products", "olist_products_dataset.csv"),
)
HISTORY: tuple[tuple[str, str], ...] = (
    ("orders", "olist_orders_dataset.csv"),
    ("order_items", "olist_order_items_dataset.csv"),
    ("payments", "olist_order_payments_dataset.csv"),
    ("reviews", "olist_order_reviews_dataset.csv"),
)
SHIFTED_COLUMNS: dict[str, tuple[str, ...]] = {
    "orders": (
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ),
    "order_items": ("shipping_limit_date",),
    "reviews": ("review_creation_date", "review_answer_timestamp"),
}

CHUNK = 1 << 20

# Status timestamps in the source are not always monotonic: 1 359 orders reach the carrier
# before they are approved. Firing events in that order would walk an order backwards through
# its lifecycle, so each step is pushed to at least one second after the previous one. The row
# still stores the source timestamp; only the firing order is corrected.
TIMELINE = """
with a as (
    select order_id, order_status,
           order_purchase_timestamp as t0,
           case when order_approved_at is not null
                then greatest(order_approved_at,
                              order_purchase_timestamp + interval '1 second') end as t1,
           order_delivered_carrier_date as carrier,
           order_delivered_customer_date as customer
    from replay.orders
),
b as (
    select a.*, case when carrier is not null
                     then greatest(carrier, coalesce(t1, t0) + interval '1 second') end as t2
    from a
),
tl as (
    select b.*, case when customer is not null
                     then greatest(customer, coalesce(t2, t1, t0) + interval '1 second') end as t3
    from b
)
"""

SCHEDULE = (
    TIMELINE
    + """
insert into replay.schedule (due_ts, kind, order_id, detail)
select t0, 'order_insert', order_id, null from tl
union all
select t1, 'order_status', order_id, 'approved' from tl where t1 is not null
union all
select t2, 'order_status', order_id, 'shipped' from tl where t2 is not null
union all
select t3, 'order_status', order_id, 'delivered' from tl where t3 is not null
union all
-- The status the dataset actually ends on, when the timeline above never reaches it:
-- canceled, unavailable, invoiced, processing.
select coalesce(t3, t2, t1, t0) + interval '1 minute', 'order_status', order_id, order_status
from tl
where order_status <> case
    when t3 is not null then 'delivered'
    when t2 is not null then 'shipped'
    when t1 is not null then 'approved'
    else 'created' end
union all
-- Cancelling before anything shipped releases the reserved items: a real DELETE for silver.
select coalesce(t3, t2, t1, t0) + interval '2 minutes', 'items_delete', order_id, null
from tl
where order_status = 'canceled' and t2 is null
union all
-- 74 reviews are dated before their own order; clamp so the foreign key can hold.
select greatest(r.review_creation_date, tl.t0 + interval '1 second'),
       'review_insert', r.order_id, r.review_id
from replay.reviews r join tl on tl.order_id = r.order_id
union all
-- A thin deterministic slice of reviews is withdrawn later, so deletes are not only a
-- cancellation story. md5 prefix keeps the choice stable across reloads.
select greatest(r.review_creation_date, tl.t0 + interval '1 second') + interval '3 days',
       'review_delete', r.order_id, r.review_id
from replay.reviews r join tl on tl.order_id = r.order_id
where substr(md5(r.review_id), 1, 2) = '00'
"""
)


def raw_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "./data")) / "raw"


Conn = state.Conn


def columns_of(conn: Conn, schema: str, table: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "select column_name from information_schema.columns "
            "where table_schema = %s and table_name = %s",
            (schema, table),
        )
        return {str(row[0]) for row in cur.fetchall()}


def header_of(path: Path) -> list[str]:
    # utf-8-sig: product_category_name_translation.csv ships a BOM, and the orders family may
    # pick one up too if the archive is ever re-exported.
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return next(csv.reader(fh))


def scalar(conn: Conn, sql: str, params: tuple[object, ...] = ()) -> object:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return row[0] if row else None


def row_count(conn: Conn, schema: str, table: str) -> int:
    return cast(int, scalar(conn, f"select count(*) from {schema}.{table}"))


def copy_table(conn: Conn, schema: str, table: str, path: Path) -> int:
    header = header_of(path)
    unknown = set(header) - columns_of(conn, schema, table)
    if unknown:
        raise SystemExit(f"{path.name}: columns missing from {schema}.{table}: {sorted(unknown)}")
    collist = ", ".join(f'"{c}"' for c in header)
    statement = (
        f"copy {schema}.{table} ({collist}) from stdin with (format csv, header true, null '')"
    )
    with conn.cursor() as cur, path.open("rb") as fh, cur.copy(statement) as cp:
        while chunk := fh.read(CHUNK):
            cp.write(chunk)
    conn.commit()
    return row_count(conn, schema, table)


def shift_staging(conn: Conn, shift: timedelta) -> None:
    with conn.cursor() as cur:
        for table, columns in SHIFTED_COLUMNS.items():
            assignments = ", ".join(f"{c} = {c} + %s" for c in columns)
            cur.execute(f"update replay.{table} set {assignments}", (shift,) * len(columns))
    conn.commit()


def promote_initial(conn: Conn, cutoff: datetime) -> dict[str, int]:
    """Move everything at or before the cutoff out of staging and into `shop`."""
    moved: dict[str, int] = {}
    with conn.cursor() as cur:
        cur.execute(
            "insert into shop.orders select * from replay.orders "
            "where order_purchase_timestamp <= %s",
            (cutoff,),
        )
        moved["orders"] = cur.rowcount
        for child in ("order_items", "payments", "reviews"):
            cur.execute(
                f"insert into shop.{child} select c.* from replay.{child} c "
                f"join shop.orders o on o.order_id = c.order_id"
            )
            moved[child] = cur.rowcount
            cur.execute(
                f"delete from replay.{child} c using shop.orders o where o.order_id = c.order_id"
            )
        cur.execute("delete from replay.orders s using shop.orders o where o.order_id = s.order_id")
    conn.commit()
    return moved


def main() -> int:
    settings = Settings()
    directory = raw_dir()
    missing = [n for _, n in (*REFERENCE, *HISTORY) if not (directory / n).is_file()]
    if missing:
        print(f"missing in {directory}: {', '.join(missing)}; run `make data`", file=sys.stderr)
        return 1

    with psycopg.connect(settings.dsn) as conn:
        state.ensure_schema(conn)
        occupied = [t for t in ("orders", "customers") if row_count(conn, "shop", t)]
        if occupied:
            print(
                f"shop.{occupied[0]} already holds rows; this loader never deletes. "
                "Run `make replay-reset` first if you mean to start over.",
                file=sys.stderr,
            )
            return 1

        for table, filename in REFERENCE:
            print(f"shop.{table:12} {copy_table(conn, 'shop', table, directory / filename):>7}")
        for table, filename in HISTORY:
            print(f"replay.{table:12} {copy_table(conn, 'replay', table, directory / filename):>5}")

        shift = cast(
            timedelta,
            scalar(
                conn,
                "select (now() at time zone 'utc') - max(order_purchase_timestamp) "
                "from replay.orders",
            ),
        )
        shift_staging(conn, shift)
        cutoff = cast(
            datetime,
            scalar(
                conn,
                "select percentile_disc(%s) within group (order by order_purchase_timestamp) "
                "from replay.orders",
                (settings.replay_initial_share,),
            ),
        )
        moved = promote_initial(conn, cutoff)
        print(f"initial load at cutoff {cutoff:%Y-%m-%d %H:%M}: {moved}")

        with conn.cursor() as cur:
            cur.execute(SCHEDULE)
            scheduled = cur.rowcount
        conn.commit()
        horizon = cast(datetime, scalar(conn, "select max(due_ts) from replay.schedule"))
        with conn.cursor() as cur:
            cur.execute(
                "insert into replay.state (shift, cutoff_ts, horizon_ts, virtual_now) "
                "values (%s, %s, %s, %s) on conflict (only_row) do update set "
                "shift = excluded.shift, cutoff_ts = excluded.cutoff_ts, "
                "horizon_ts = excluded.horizon_ts, virtual_now = excluded.virtual_now, "
                "events_emitted = 0, loaded_at = now(), started_at = null",
                (shift, cutoff, horizon, cutoff),
            )
        conn.commit()
        print(f"scheduled {scheduled} events up to {horizon:%Y-%m-%d %H:%M}")
        print(f"dates shifted by {shift.days} days")
    return 0


if __name__ == "__main__":
    sys.exit(main())
