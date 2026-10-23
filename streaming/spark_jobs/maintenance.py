"""Iceberg maintenance of the lake (W5-T05a, ADR-025): expire snapshots, remove orphan files,
rewrite position deletes, compact data files.

    run-job.sh maintenance expire --days 7 silver.sellers silver.orders
    run-job.sh maintenance orphans [--no-dry-run] [--location-suffix metadata] <tables>
    run-job.sh maintenance rewrite-position-deletes silver.orders
    run-job.sh maintenance rewrite-data --before-today lake.bronze.cdc_events

The rules are checked here, before a Spark session starts, not only in the DAG that calls this:
bronze never loses a snapshot (ADR-021), silver and gold keep a week, and an orphan file younger
than a week may be a commit in flight. Each call prints one JSON line. A failing table does not
stop the others; the exit code is then 1.

The top of the file needs no JVM, so the rules are tested on the host. Python 3.10 (the image).
"""

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pyspark.sql import SparkSession

CATALOG = "lake"
LAYERS = ("bronze", "silver", "gold", "demo")
SANDBOX = "demo"
MIN_RETENTION_DAYS = 7
DEFAULT_DAYS = 7
BRONZE_ORPHAN_SUFFIX = "metadata"
# The partition column of bronze; --before-today limits a compaction to its past days.
DAY_COLUMN = "ingest_ts"
MAX_LISTED_FILES = 200


class PolicyError(ValueError):
    """A request the maintenance policy forbids."""


def parse_table(raw: str) -> str:
    """`silver.sellers` or `lake.silver.sellers` as `lake.silver.sellers`. Only plain names pass:
    the text goes into SQL."""
    parts = raw.strip().lower().split(".")
    if parts[0] == CATALOG:
        parts = parts[1:]
    names_ok = len(parts) == 2 and all(
        p and (p[0].isalpha() or p[0] == "_") and p.replace("_", "").isalnum() and p.isascii()
        for p in parts
    )
    if not names_ok or parts[0] not in LAYERS:
        raise PolicyError(f"{raw!r} is not <{'|'.join(LAYERS)}>.<table>")
    return ".".join([CATALOG, *parts])


def procedure_table(table: str) -> str:
    """The name Iceberg procedures take: without the catalog."""
    return table.removeprefix(f"{CATALOG}.")


def layer(table: str) -> str:
    return procedure_table(table).split(".")[0]


def check_expire(table: str, days: int) -> None:
    if layer(table) == "bronze":
        raise PolicyError(
            f"expire_snapshots on {table} is forbidden: it breaks the streaming read of silver "
            "(ADR-021, apache/iceberg#18000)"
        )
    if layer(table) != SANDBOX and days < MIN_RETENTION_DAYS:
        raise PolicyError(
            f"expire_snapshots on {table} keeps at least {MIN_RETENTION_DAYS} days, got {days} "
            "(Trino refuses less too, ADR-025)"
        )


def check_orphans(table: str, days: int, location_suffix: str | None) -> None:
    if layer(table) == "bronze" and location_suffix != BRONZE_ORPHAN_SUFFIX:
        raise PolicyError(
            f"remove_orphan_files on {table} only with --location-suffix {BRONZE_ORPHAN_SUFFIX}: "
            "bronze data files are never deleted, Kafka no longer has them (ADR-021, ADR-005)"
        )
    if layer(table) != SANDBOX and days < MIN_RETENTION_DAYS:
        raise PolicyError(
            f"remove_orphan_files on {table} only for files older than {MIN_RETENTION_DAYS} days, "
            f"got {days}: a younger one may belong to a commit in flight (ADR-025)"
        )


def check_rewrite_data(table: str, before_today: bool) -> None:
    if layer(table) == "bronze" and not before_today:
        raise PolicyError(
            f"rewrite_data_files on {table} only with --before-today: today's partitions are "
            "still being committed by the stream"
        )


def older_than_literal(now: datetime, days: int) -> str:
    """CALL accepts only literals, so the time is formatted, in UTC like the session."""
    if now.tzinfo is None:
        raise ValueError("older_than needs a time with a zone")
    moment = (now - timedelta(days=days)).astimezone(timezone.utc)  # noqa: UP017
    return f"TIMESTAMP '{moment.strftime('%Y-%m-%d %H:%M:%S.%f')}'"


def before_today_filter(now: datetime) -> str:
    midnight = now.astimezone(timezone.utc).strftime("%Y-%m-%d 00:00:00")  # noqa: UP017
    return f"{DAY_COLUMN} < TIMESTAMP '{midnight}'"


def sql_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def call(procedure: str, **arguments: str) -> str:
    pairs = ", ".join(f"{name} => {value}" for name, value in arguments.items())
    return f"call {CATALOG}.system.{procedure}({pairs})"


def expire_sql(table: str, older_than: str, retain_last: int) -> str:
    return call(
        "expire_snapshots",
        table=sql_string(procedure_table(table)),
        older_than=older_than,
        retain_last=str(retain_last),
    )


def orphans_sql(table: str, older_than: str, dry_run: bool, location: str | None) -> str:
    arguments = {
        "table": sql_string(procedure_table(table)),
        "older_than": older_than,
        "dry_run": "true" if dry_run else "false",
    }
    if location is not None:
        arguments["location"] = sql_string(location)
    return call("remove_orphan_files", **arguments)


def orphan_location(table_location: str, suffix: str | None) -> str | None:
    if suffix is None:
        return None
    return f"{table_location.rstrip('/')}/{suffix}"


def rewrite_position_deletes_sql(table: str) -> str:
    return call("rewrite_position_delete_files", table=sql_string(procedure_table(table)))


def rewrite_data_sql(table: str, where: str | None, options: Mapping[str, str]) -> str:
    arguments = {"table": sql_string(procedure_table(table))}
    if where is not None:
        # Double quotes outside: the filter holds a quoted timestamp literal.
        arguments["where"] = '"' + where + '"'
    if options:
        pairs = ", ".join(f"{sql_string(k)}, {sql_string(v)}" for k, v in options.items())
        arguments["options"] = f"map({pairs})"
    return call("rewrite_data_files", **arguments)


def result_line(op: str, table: str, rows: Sequence[Mapping[str, Any]], **extra: Any) -> str:
    """One line per call. For orphans, `candidates` (dry run) or `removed` and the file list."""
    payload: dict[str, Any] = {"op": op, "table": table, **extra}
    if op == "orphans":
        files = [str(r["orphan_file_location"]) for r in rows]
        payload["candidates" if extra.get("dry_run") else "removed"] = len(files)
        payload["files"] = files[:MAX_LISTED_FILES]
        payload["files_truncated"] = len(files) > MAX_LISTED_FILES
    elif rows:
        payload.update(rows[0])
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def error_line(op: str, table: str, error: BaseException) -> str:
    message = " ".join(f"{type(error).__name__}: {error}".split())
    return json.dumps({"op": op, "table": table, "error": message}, separators=(",", ":"))


def run_tables(
    op: str,
    tables: Sequence[str],
    action: Callable[[str], Sequence[Mapping[str, Any]]],
    out: Callable[[str], object] = print,
    **extra: Any,
) -> int:
    """Run `action` per table; a failure is reported and the next table still runs. 1 on any."""
    failed = 0
    for table in tables:
        try:
            out(result_line(op, table, action(table), **extra))
        except Exception as error:  # reported per table, exit code 1 at the end
            failed += 1
            out(error_line(op, table, error))
    return 1 if failed else 0


def non_negative(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="maintenance", description="Iceberg maintenance of the lake"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    expire = commands.add_parser("expire", help="expire_snapshots, the latest snapshot stays")
    expire.add_argument("--days", type=non_negative, default=DEFAULT_DAYS)
    expire.add_argument("--retain-last", type=int, default=1)

    deletes = commands.add_parser(
        "rewrite-position-deletes", help="fold position delete files (merge-on-read tables)"
    )
    deletes.set_defaults(days=None)

    data = commands.add_parser("rewrite-data", help="rewrite_data_files: compact small files")
    data.add_argument(
        "--before-today",
        action="store_true",
        help=f"only partitions with {DAY_COLUMN} before today's midnight UTC",
    )
    data.add_argument("--option", action="append", default=[], metavar="KEY=VALUE")

    orphans = commands.add_parser(
        "orphans", help="remove_orphan_files; a dry run unless --no-dry-run"
    )
    orphans.add_argument("--days", type=non_negative, default=DEFAULT_DAYS)
    orphans.add_argument("--location-suffix", default=None, help="a directory of the table")
    orphans.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True)

    for sub in (expire, deletes, data, orphans):
        sub.add_argument("tables", nargs="+")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def validate(args: argparse.Namespace) -> list[str]:
    """Every table of the command, checked against the policy. Raises PolicyError."""
    tables = [parse_table(raw) for raw in args.tables]
    for table in tables:
        if args.command == "expire":
            check_expire(table, args.days)
        elif args.command == "orphans":
            check_orphans(table, args.days, args.location_suffix)
        elif args.command == "rewrite-data":
            check_rewrite_data(table, args.before_today)
    return tables


def table_location(spark: "SparkSession", table: str) -> str:
    """The table's directory, from the newest metadata file it has logged: the catalog gives no
    `location` property in `show tblproperties` on every setup, the metadata log is plain SQL."""
    rows = spark.sql(
        f"select file from {table}.metadata_log_entries order by timestamp desc limit 1"
    ).collect()
    if not rows:
        raise RuntimeError(f"{table} has no metadata log")
    directory, _, _ = str(rows[0]["file"]).rpartition("/")
    location, _, leaf = directory.rpartition("/")
    if leaf != "metadata":
        raise RuntimeError(f"cannot tell the location of {table} from {rows[0]['file']}")
    return location


def execute(
    spark: "SparkSession", args: argparse.Namespace, table: str, now: datetime
) -> list[dict[str, Any]]:
    """The procedure of the command for one table; its result rows as dicts."""
    if args.command == "expire":
        sql = expire_sql(table, older_than_literal(now, args.days), args.retain_last)
    elif args.command == "orphans":
        suffix = args.location_suffix
        location = orphan_location(table_location(spark, table), suffix) if suffix else None
        sql = orphans_sql(table, older_than_literal(now, args.days), args.dry_run, location)
    elif args.command == "rewrite-position-deletes":
        sql = rewrite_position_deletes_sql(table)
    else:
        options = dict(item.split("=", 1) for item in args.option)
        where = before_today_filter(now) if args.before_today else None
        sql = rewrite_data_sql(table, where, options)
    print(sql, file=sys.stderr)
    return [row.asDict() for row in spark.sql(sql).collect()]


def open_session() -> "SparkSession":
    from spark_jobs.catalog import build_session
    from spark_jobs.settings import Settings

    spark = build_session("maintenance", Settings())
    spark.sparkContext.setLogLevel("WARN")
    # older_than literals are UTC.
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    return spark


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        tables = validate(args)
    except PolicyError as error:
        print(f"maintenance refused: {error}", file=sys.stderr)
        return 1
    spark = open_session()
    try:
        now = datetime.now(timezone.utc)  # noqa: UP017
        extra = {"dry_run": args.dry_run} if args.command == "orphans" else {}
        return run_tables(
            args.command, tables, lambda table: execute(spark, args, table, now), **extra
        )
    finally:
        spark.stop()


if __name__ == "__main__":
    sys.exit(main())
