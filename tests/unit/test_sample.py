"""The committed sample must stay referentially closed, or every test built on it lies."""

import csv
from pathlib import Path

import pytest

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample"


def rows(filename: str) -> list[dict[str, str]]:
    with (SAMPLE / filename).open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def orders() -> list[dict[str, str]]:
    return rows("olist_orders_dataset.csv")


@pytest.fixture(scope="module")
def items() -> list[dict[str, str]]:
    return rows("olist_order_items_dataset.csv")


def test_sample_holds_two_thousand_distinct_orders(orders: list[dict[str, str]]) -> None:
    assert len(orders) == 2000
    assert len({r["order_id"] for r in orders}) == 2000


@pytest.mark.parametrize(
    ("filename", "column"),
    [
        ("olist_order_items_dataset.csv", "order_id"),
        ("olist_order_payments_dataset.csv", "order_id"),
        ("olist_order_reviews_dataset.csv", "order_id"),
    ],
)
def test_children_reference_sampled_orders(
    filename: str, column: str, orders: list[dict[str, str]]
) -> None:
    known = {r["order_id"] for r in orders}
    assert {r[column] for r in rows(filename)} <= known


def test_orders_reference_sampled_customers(orders: list[dict[str, str]]) -> None:
    known = {r["customer_id"] for r in rows("olist_customers_dataset.csv")}
    assert {r["customer_id"] for r in orders} <= known


@pytest.mark.parametrize(
    ("column", "parent_file", "parent_key"),
    [
        ("product_id", "olist_products_dataset.csv", "product_id"),
        ("seller_id", "olist_sellers_dataset.csv", "seller_id"),
    ],
)
def test_items_reference_sampled_parents(
    column: str, parent_file: str, parent_key: str, items: list[dict[str, str]]
) -> None:
    known = {r[parent_key] for r in rows(parent_file)}
    assert {r[column] for r in items} <= known


@pytest.mark.parametrize(
    ("filename", "key"),
    [
        ("olist_order_items_dataset.csv", ("order_id", "order_item_id")),
        ("olist_order_payments_dataset.csv", ("order_id", "payment_sequential")),
        # review_id repeats in the source, so only the pair is unique; shop.reviews keys on it.
        ("olist_order_reviews_dataset.csv", ("review_id", "order_id")),
    ],
)
def test_composite_keys_are_unique(filename: str, key: tuple[str, ...]) -> None:
    data = rows(filename)
    assert len({tuple(r[c] for c in key) for r in data}) == len(data)


def test_review_text_keeps_its_trailing_whitespace() -> None:
    """A whitespace-fixing pre-commit hook once rewrote 24 lines of this file.

    The sample has to stay byte-faithful to the source, so guard the property in CI rather
    than rely on the hook exclusion staying in place.
    """
    ragged = 0
    for row in rows("olist_order_reviews_dataset.csv"):
        message = row["review_comment_message"] or ""
        if any(line != line.rstrip() for line in message.splitlines()):
            ragged += 1
    assert ragged > 0
