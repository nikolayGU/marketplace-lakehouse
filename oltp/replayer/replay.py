"""Walk the schedule in virtual time, writing real INSERT, UPDATE and DELETE into `shop`.

The clock resumes from `replay.state.virtual_now`, so a restart continues where the previous
process stopped instead of replaying from the top or racing to catch up with wall time.
A batch is selected, executed and marked emitted in one transaction: a crash rolls the whole
batch back and it runs again, and every statement is written to tolerate that.
"""

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import psycopg

from replayer import server, state
from replayer.settings import Settings

log = logging.getLogger("replayer")


class NotLoadedError(Exception):
    """Raised while `replay.state` is empty, so `start` can wait instead of crash-looping."""


Conn = state.Conn
Cur = state.Cur

CLAIM = """
select seq, due_ts, kind, order_id, detail, delayed
from replay.schedule
where emitted_at is null and due_ts <= %s
order by due_ts, seq
limit %s
for update skip locked
"""

INSERT_ORDER = """
insert into shop.orders (order_id, customer_id, order_status,
                         order_purchase_timestamp, order_estimated_delivery_date)
select order_id, customer_id, 'created', order_purchase_timestamp, order_estimated_delivery_date
from replay.orders where order_id = %s
on conflict (order_id) do nothing
"""

INSERT_CHILDREN = (
    "insert into shop.order_items select * from replay.order_items where order_id = %s "
    "on conflict (order_id, order_item_id) do nothing",
    "insert into shop.payments select * from replay.payments where order_id = %s "
    "on conflict (order_id, payment_sequential) do nothing",
)

# Each lifecycle step also fills the timestamp that proves it happened, which is what makes the
# CDC `before`/`after` pair worth reading.
STATUS_SQL: dict[str, str] = {
    "approved": "update shop.orders o set order_status = 'approved', "
    "order_approved_at = r.order_approved_at "
    "from replay.orders r where r.order_id = o.order_id and o.order_id = %s",
    "shipped": "update shop.orders o set order_status = 'shipped', "
    "order_delivered_carrier_date = r.order_delivered_carrier_date "
    "from replay.orders r where r.order_id = o.order_id and o.order_id = %s",
    "delivered": "update shop.orders o set order_status = 'delivered', "
    "order_delivered_customer_date = r.order_delivered_customer_date "
    "from replay.orders r where r.order_id = o.order_id and o.order_id = %s",
}
PLAIN_STATUS = "update shop.orders set order_status = %s where order_id = %s"

INSERT_REVIEW = (
    "insert into shop.reviews select * from replay.reviews "
    "where review_id = %s and order_id = %s on conflict (review_id, order_id) do nothing"
)
DELETE_ITEMS = "delete from shop.order_items where order_id = %s"
DELETE_REVIEW = "delete from shop.reviews where review_id = %s and order_id = %s"


@dataclass(frozen=True)
class Event:
    seq: int
    due_ts: datetime
    kind: str
    order_id: str
    detail: str | None
    delayed: bool


def picks(key: str, salt: str, ratio: float) -> bool:
    """Stable share selector: the same key always lands on the same side of the same ratio."""
    if ratio <= 0:
        return False
    if ratio >= 1:
        return True
    digest = hashlib.md5(f"{salt}:{key}".encode(), usedforsecurity=False).hexdigest()[:8]
    return int(digest, 16) / 0xFFFFFFFF < ratio


class Replayer:
    def __init__(self, settings: Settings, conn: Conn) -> None:
        self.settings = settings
        self.conn = conn
        current = state.read(conn)
        if current is None:
            raise NotLoadedError
        self.state = current
        self.virtual_base = current.virtual_now
        self.real_base = time.monotonic()
        self.emitted = current.events_emitted

    def virtual_now(self) -> datetime:
        elapsed = time.monotonic() - self.real_base
        moved = self.virtual_base + timedelta(seconds=elapsed * self.settings.replay_speed)
        return min(moved, self.state.horizon_ts)

    def claim(self, cur: Cur, now: datetime) -> list[Event]:
        cur.execute(CLAIM, (now, self.settings.replay_batch_size))
        return [Event(*row) for row in cur.fetchall()]

    def postpone(self, cur: Cur, event: Event) -> None:
        cur.execute(
            "update replay.schedule set due_ts = due_ts + %s, delayed = true where seq = %s",
            (timedelta(seconds=self.settings.replay_late_delay_seconds), event.seq),
        )

    def execute(self, cur: Cur, event: Event) -> None:
        if event.kind == "order_insert":
            cur.execute(INSERT_ORDER, (event.order_id,))
            for child_sql in INSERT_CHILDREN:
                cur.execute(child_sql, (event.order_id,))
        elif event.kind == "order_status":
            status = event.detail or "created"
            sql = STATUS_SQL.get(status)
            if sql is not None:
                cur.execute(sql, (event.order_id,))
            else:
                cur.execute(PLAIN_STATUS, (status, event.order_id))
            # A byte-identical repeat still writes a new tuple version, so Debezium emits a
            # second event: a duplicate that downstream dedup has to survive.
            if picks(event.order_id, "duplicate", self.settings.replay_duplicate_ratio):
                if sql is not None:
                    cur.execute(sql, (event.order_id,))
                else:
                    cur.execute(PLAIN_STATUS, (status, event.order_id))
                server.EVENTS.labels(kind="duplicate").inc()
        elif event.kind == "review_insert":
            cur.execute(INSERT_REVIEW, (event.detail, event.order_id))
        elif event.kind == "items_delete":
            cur.execute(DELETE_ITEMS, (event.order_id,))
        elif event.kind == "review_delete":
            cur.execute(DELETE_REVIEW, (event.detail, event.order_id))
        else:
            raise SystemExit(f"unknown event kind {event.kind!r} at seq {event.seq}")

    def step(self) -> int:
        now = self.virtual_now()
        with self.conn.cursor() as cur:
            events = self.claim(cur, now)
            done: list[int] = []
            for event in events:
                late = (
                    event.kind == "order_status"
                    and event.detail == "delivered"
                    and not event.delayed
                    and picks(event.order_id, "late", self.settings.replay_late_ratio)
                )
                if late:
                    self.postpone(cur, event)
                    server.EVENTS.labels(kind="late_postponed").inc()
                    continue
                self.execute(cur, event)
                done.append(event.seq)
                server.EVENTS.labels(kind=event.kind).inc()
            if done:
                cur.execute(
                    "update replay.schedule set emitted_at = now() where seq = any(%s)", (done,)
                )
            cur.execute(
                "update replay.state set virtual_now = %s, events_emitted = events_emitted + %s",
                (now, len(done)),
            )
        self.conn.commit()
        self.emitted += len(done)
        server.VIRTUAL_NOW.set(now.timestamp())
        return len(events)

    def pending(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute("select count(*) from replay.schedule where emitted_at is null")
            row = cur.fetchone()
        return int(row[0]) if row else 0

    def status(self) -> dict[str, object]:
        return {
            "virtual_now": self.virtual_now(),
            "horizon": self.state.horizon_ts,
            "cutoff": self.state.cutoff_ts,
            "shift_days": self.state.shift.days,
            "speed": self.settings.replay_speed,
            "events_emitted": self.emitted,
            "finished": self.virtual_now() >= self.state.horizon_ts,
        }


def run(settings: Settings) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    with psycopg.connect(settings.dsn) as conn:
        state.ensure_schema(conn)
        server.SPEED.set(settings.replay_speed)
        # The container may come up before anyone has run `load`. Bind the port once and swap
        # what /status reports, rather than exiting into a restart loop or rebinding later.
        report: list[Callable[[], dict[str, object]]] = [lambda: {"state": "waiting for load"}]
        server.serve(settings.http_port, lambda: report[0]())
        replayer = None
        while replayer is None:
            try:
                replayer = Replayer(settings, conn)
            except NotLoadedError:
                log.info("no replay state yet; waiting for `replayer load`")
                time.sleep(5)
        report[0] = replayer.status
        with conn.cursor() as cur:
            cur.execute("update replay.state set started_at = coalesce(started_at, now())")
        conn.commit()
        log.info(
            "replaying from %s to %s at %sx",
            replayer.virtual_base,
            replayer.state.horizon_ts,
            settings.replay_speed,
        )
        idle_logged = False
        while True:
            claimed = replayer.step()
            pending = replayer.pending()
            server.PENDING.set(pending)
            if pending == 0:
                if not idle_logged:
                    log.info("schedule drained after %s events; idling", replayer.emitted)
                    idle_logged = True
                time.sleep(5)
                continue
            time.sleep(0.05 if claimed else 0.5)
