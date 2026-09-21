"""Replay bookkeeping: the staging copy of the un-replayed history and the resume point.

Everything here lives in schema `replay`, outside `shop`, for one concrete reason: the CDC
publication is declared `for tables in schema shop`, so anything put in `shop` would be decoded
into the replication slot on every write. The replayer touches its own state constantly, and
none of that belongs in the change stream.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import psycopg

# psycopg hands back untyped rows; one alias keeps every module honest about that.
Row = tuple[Any, ...]
Conn = psycopg.Connection[Row]
Cur = psycopg.Cursor[Row]

SCHEMA = """
create schema if not exists replay;

-- Staging holds the history that has not been replayed yet, already date-shifted. Columns are
-- copied from shop, constraints are not: these rows reference orders that are not inserted yet.
create table if not exists replay.orders (like shop.orders including defaults);
create table if not exists replay.order_items (like shop.order_items including defaults);
create table if not exists replay.payments (like shop.payments including defaults);
create table if not exists replay.reviews (like shop.reviews including defaults);

create index if not exists replay_orders_purchase_idx
    on replay.orders (order_purchase_timestamp);
create index if not exists replay_order_items_order_idx on replay.order_items (order_id);
create index if not exists replay_payments_order_idx on replay.payments (order_id);
create index if not exists replay_reviews_order_idx on replay.reviews (order_id);

-- One row per thing that has to happen, in virtual time. Emitting is idempotent by
-- `emitted_at`, which is what makes a restart continue instead of replaying from the top.
create table if not exists replay.schedule (
    seq bigserial primary key,
    due_ts timestamp not null,
    kind text not null,
    order_id varchar(32) not null,
    detail text,
    -- Set once when the late-event knob pushes an event forward, so it is not pushed twice.
    delayed boolean not null default false,
    emitted_at timestamptz
);

create index if not exists replay_schedule_pending_idx
    on replay.schedule (due_ts, seq) where emitted_at is null;

create table if not exists replay.state (
    only_row boolean primary key default true check (only_row),
    shift interval not null,
    cutoff_ts timestamp not null,
    horizon_ts timestamp not null,
    virtual_now timestamp not null,
    events_emitted bigint not null default 0,
    loaded_at timestamptz not null default now(),
    started_at timestamptz
);
"""


@dataclass(frozen=True)
class State:
    shift: timedelta
    cutoff_ts: datetime
    horizon_ts: datetime
    virtual_now: datetime
    events_emitted: int
    started_at: datetime | None

    @property
    def finished(self) -> bool:
        return self.virtual_now >= self.horizon_ts


def ensure_schema(conn: Conn) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
    conn.commit()


def read(conn: Conn) -> State | None:
    with conn.cursor() as cur:
        cur.execute(
            "select shift, cutoff_ts, horizon_ts, virtual_now, events_emitted, started_at "
            "from replay.state"
        )
        row = cur.fetchone()
    if row is None:
        return None
    return State(
        shift=row[0],
        cutoff_ts=row[1],
        horizon_ts=row[2],
        virtual_now=row[3],
        events_emitted=row[4],
        started_at=row[5],
    )
