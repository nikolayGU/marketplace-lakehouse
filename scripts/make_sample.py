"""Cut a 2 000-order slice of the Olist dataset into `data/sample`.

The slice is referentially closed: every customer, product and seller a sampled order touches
is carried over, so the same loader and the same foreign keys work on it. The order ids are
drawn with a fixed seed, so regenerating the sample produces the same rows.
"""

import csv
import os
import random
import sys
from collections.abc import Iterable
from pathlib import Path

SEED = 20260919
ORDERS = 2000

ORDERS_FILE = "olist_orders_dataset.csv"
CHILDREN = (
    ("olist_order_items_dataset.csv", "order_id"),
    ("olist_order_payments_dataset.csv", "order_id"),
    ("olist_order_reviews_dataset.csv", "order_id"),
)
PARENTS = (
    ("olist_customers_dataset.csv", "customer_id"),
    ("olist_products_dataset.csv", "product_id"),
    ("olist_sellers_dataset.csv", "seller_id"),
)
VERBATIM = ("product_category_name_translation.csv",)

Row = dict[str, str]


def read(path: Path) -> tuple[list[str], list[Row]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        return fields, list(reader)


def write(path: Path, fields: list[str], rows: Iterable[Row]) -> int:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        count = 0
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def main() -> int:
    data = Path(os.environ.get("DATA_DIR", "./data"))
    raw, sample = data / "raw", data / "sample"
    if not (raw / ORDERS_FILE).is_file():
        print(f"{raw / ORDERS_FILE} not found; run `make data`", file=sys.stderr)
        return 1
    sample.mkdir(parents=True, exist_ok=True)

    order_fields, orders = read(raw / ORDERS_FILE)
    chosen = set(random.Random(SEED).sample(sorted(r["order_id"] for r in orders), ORDERS))
    kept_orders = [r for r in orders if r["order_id"] in chosen]
    print(f"{ORDERS_FILE:42} {write(sample / ORDERS_FILE, order_fields, kept_orders):>6}")

    # Parents are collected from the order rows and from the items of those orders.
    needed: dict[str, set[str]] = {"customer_id": {r["customer_id"] for r in kept_orders}}
    for filename, key in CHILDREN:
        fields, rows = read(raw / filename)
        kept = [r for r in rows if r[key] in chosen]
        if filename == "olist_order_items_dataset.csv":
            needed["product_id"] = {r["product_id"] for r in kept}
            needed["seller_id"] = {r["seller_id"] for r in kept}
        print(f"{filename:42} {write(sample / filename, fields, kept):>6}")

    for filename, key in PARENTS:
        fields, rows = read(raw / filename)
        kept = [r for r in rows if r[key] in needed[key]]
        print(f"{filename:42} {write(sample / filename, fields, kept):>6}")

    for filename in VERBATIM:
        fields, rows = read(raw / filename)
        print(f"{filename:42} {write(sample / filename, fields, rows):>6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
