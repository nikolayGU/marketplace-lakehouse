"""Entry point: `python -m replayer <command>`."""

import argparse
import json
import sys

import psycopg

from replayer import load, migrations, replay, state
from replayer.settings import Settings

TRUNCATE = """
truncate shop.reviews, shop.payments, shop.order_items, shop.orders,
         shop.products, shop.sellers, shop.customers;
drop schema if exists replay cascade;
"""


def cmd_status(settings: Settings) -> int:
    with psycopg.connect(settings.dsn) as conn:
        state.ensure_schema(conn)
        current = state.read(conn)
        if current is None:
            print("no replay state; run `make replay-load`")
            return 1
        with conn.cursor() as cur:
            cur.execute("select count(*) from replay.schedule where emitted_at is null")
            row = cur.fetchone()
        pending = int(row[0]) if row else 0
    print(
        json.dumps(
            {
                "cutoff": current.cutoff_ts,
                "virtual_now": current.virtual_now,
                "horizon": current.horizon_ts,
                "shift_days": current.shift.days,
                "events_emitted": current.events_emitted,
                "events_pending": pending,
                "started_at": current.started_at,
                "finished": current.finished,
            },
            default=str,
            indent=2,
        )
    )
    return 0


def cmd_reset(settings: Settings) -> int:
    """Destructive: empties `shop` and drops the staging schema. Guarded by --yes."""
    with psycopg.connect(settings.dsn) as conn, conn.cursor() as cur:
        cur.execute(TRUNCATE)
        conn.commit()
    print("shop emptied and replay staging dropped; run load again")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="replayer")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply oltp/migrations")
    sub.add_parser("load", help="shift dates, bulk-load the initial share, build the schedule")
    sub.add_parser("start", help="replay the remaining history on the virtual clock")
    sub.add_parser("status", help="print the replay position")
    reset = sub.add_parser("reset", help="empty shop and drop staging (destructive)")
    reset.add_argument("--yes", action="store_true", help="required; there is no undo")
    args = parser.parse_args(argv)

    settings = Settings()
    if args.command == "migrate":
        return migrations.main()
    if args.command == "load":
        return load.main()
    if args.command == "start":
        return replay.run(settings)
    if args.command == "status":
        return cmd_status(settings)
    if args.command == "reset":
        if not args.yes:
            print("refusing without --yes: this empties every shop table", file=sys.stderr)
            return 1
        return cmd_reset(settings)
    return 1


if __name__ == "__main__":
    sys.exit(main())
