"""Bulk-load the Olist CSVs into schema `shop` with COPY.

Tables are filled parents first so the foreign keys hold at every step. A table that already
has rows is left alone: this loader never deletes anything, so re-running it after a partial
load is safe but will not repair one.
"""

import csv
import os
import sys
from pathlib import Path
from typing import cast

import psycopg

from replayer.settings import Settings

# Load order matters: every table here only references tables above it.
SOURCES: tuple[tuple[str, str], ...] = (
    ("customers", "olist_customers_dataset.csv"),
    ("sellers", "olist_sellers_dataset.csv"),
    ("products", "olist_products_dataset.csv"),
    ("orders", "olist_orders_dataset.csv"),
    ("order_items", "olist_order_items_dataset.csv"),
    ("payments", "olist_order_payments_dataset.csv"),
    ("reviews", "olist_order_reviews_dataset.csv"),
)

CHUNK = 1 << 20


def raw_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "./data")) / "raw"


def columns_of(conn: psycopg.Connection[tuple[object, ...]], table: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "select column_name from information_schema.columns "
            "where table_schema = 'shop' and table_name = %s",
            (table,),
        )
        return {str(row[0]) for row in cur.fetchall()}


def header_of(path: Path) -> list[str]:
    # utf-8-sig: product_category_name_translation.csv ships a BOM, and the orders family may
    # pick one up too if the archive is ever re-exported.
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return next(csv.reader(fh))


def row_count(conn: psycopg.Connection[tuple[object, ...]], table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"select count(*) from shop.{table}")
        row = cur.fetchone()
    return cast(int, row[0]) if row else 0


def copy_table(conn: psycopg.Connection[tuple[object, ...]], table: str, path: Path) -> int:
    header = header_of(path)
    unknown = set(header) - columns_of(conn, table)
    if unknown:
        raise SystemExit(f"{path.name}: columns not present in shop.{table}: {sorted(unknown)}")
    collist = ", ".join(f'"{c}"' for c in header)
    statement = f"copy shop.{table} ({collist}) from stdin with (format csv, header true, null '')"
    with conn.cursor() as cur, path.open("rb") as fh, cur.copy(statement) as cp:
        while chunk := fh.read(CHUNK):
            cp.write(chunk)
    conn.commit()
    return row_count(conn, table)


def main() -> int:
    directory = raw_dir()
    missing = [name for _, name in SOURCES if not (directory / name).is_file()]
    if missing:
        print(f"missing in {directory}: {', '.join(missing)}; run `make data`", file=sys.stderr)
        return 1

    with psycopg.connect(Settings().dsn) as conn:
        for table, filename in SOURCES:
            existing = row_count(conn, table)
            if existing:
                print(f"shop.{table:12} skipped, already holds {existing} rows")
                continue
            loaded = copy_table(conn, table, directory / filename)
            print(f"shop.{table:12} loaded {loaded} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
