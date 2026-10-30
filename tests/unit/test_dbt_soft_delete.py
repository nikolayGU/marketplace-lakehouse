"""Every model that reads a staging model drops its deleted rows (D4).

Staging keeps every row with `is_deleted`; each model that reads it decides. The dbt test
`dbt/tests/assert_gold_has_no_deleted_entities.sql` proves it on the data, but only on a live
stack, and it catches a lost filter only when a deleted entity exists. This reads the SQL, so a
dropped `where not is_deleted` fails on the host.

Scope: the models in `intermediate/` and `marts/` that `ref('stg_*')`. Readers of
`fct_order_items` are not scanned: it keeps deleted items on purpose, and `canceled_gmv` (D8) in
`int_daily_sales` sums them.
"""

import re
from pathlib import Path

import pytest

MODELS = Path(__file__).resolve().parents[2] / "dbt" / "models"
CONSUMERS = sorted([*(MODELS / "intermediate").glob("*.sql"), *(MODELS / "marts").glob("*.sql")])

# SQL line and block comments and Jinja comments: none of them is a filter.
COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/|\{#.*?#\}", re.DOTALL)
STAGING_REF = re.compile(r"ref\('(stg_\w+)'\)")
NOT_DELETED = re.compile(r"\bnot\s+(?:\w+\.)?is_deleted\b")
WHERE = re.compile(r"\bwhere\b(.*?)(?=\bgroup\s+by\b|\border\s+by\b|\Z)", re.DOTALL)
AGGREGATE = re.compile(r"\b(sum|count_if|count|avg|min|max|arbitrary|array_agg|approx_\w+)\(")

KEEPS_DELETED_ROWS = "fct_order_items"
# stg_order_items has no row filter in int_orders_enriched: its aggregates count live items only,
# and updated_at covers deleted ones too, since deleting an item changes the order for the marts.
AGGREGATES_ONLY = {("int_orders_enriched", "stg_order_items")}
# What a mutation must not be able to hide by deleting the model from the scan.
GUARDED = {
    ("int_orders_enriched", "stg_orders"),
    ("int_orders_enriched", "stg_customers"),
    ("int_orders_enriched", "stg_payments"),
    ("dim_customers", "stg_orders"),
    ("dim_customers", "stg_customers"),
    ("dim_products", "stg_products"),
    ("dim_sellers", "stg_sellers"),
    ("mart_seller_performance", "stg_reviews"),
}


def without_comments(sql: str) -> str:
    return COMMENT.sub("", sql)


def readings() -> list[tuple[str, str, str]]:
    """(model, staging model, the CTE or select that reads it) for every `ref('stg_*')`."""
    found = []
    for path in CONSUMERS:
        sql = without_comments(path.read_text())
        # A CTE ends on a line that starts with `)`; what follows the last one is the final select.
        for block in re.split(r"^\)", sql, flags=re.MULTILINE):
            for staging in dict.fromkeys(STAGING_REF.findall(block)):
                found.append((path.stem, staging, block))
    return found


def drops_deleted_rows(block: str) -> bool:
    return any(NOT_DELETED.search(clause) for clause in WHERE.findall(block))


def unguarded_aggregates(block: str) -> list[str]:
    """Aggregate calls over a deleted-row-keeping model that do not say `not is_deleted`."""
    unguarded = []
    for call in AGGREGATE.finditer(block):
        depth, end = 1, call.end()
        while depth:
            depth += {"(": 1, ")": -1}.get(block[end], 0)
            end += 1
        arguments = block[call.end() : end - 1]
        if call.group(1) == "max" and arguments.strip() == "updated_at":
            continue
        if not NOT_DELETED.search(arguments):
            unguarded.append(f"{call.group(1)}({arguments})")
    return unguarded


FILTERED = [r for r in readings() if r[0] != KEEPS_DELETED_ROWS and r[:2] not in AGGREGATES_ONLY]
CONDITIONAL = [r for r in readings() if r[:2] in AGGREGATES_ONLY]


def test_the_scan_reads_every_model_that_has_to_filter() -> None:
    assert {r[:2] for r in readings()} >= GUARDED | AGGREGATES_ONLY


@pytest.mark.parametrize(
    ("model", "staging", "block"), FILTERED, ids=[f"{m}:{s}" for m, s, _ in FILTERED]
)
def test_consumer_drops_the_deleted_rows_of_a_staging_model(
    model: str, staging: str, block: str
) -> None:
    assert drops_deleted_rows(block), f"{model} reads {staging} without `where not is_deleted`"


@pytest.mark.parametrize(
    ("model", "staging", "block"), CONDITIONAL, ids=[f"{m}:{s}" for m, s, _ in CONDITIONAL]
)
def test_consumer_that_keeps_deleted_rows_aggregates_live_ones_only(
    model: str, staging: str, block: str
) -> None:
    assert AGGREGATE.search(block), f"{model} reads {staging} and aggregates nothing"
    assert unguarded_aggregates(block) == [], f"{model} counts deleted {staging} rows"
    # A row filter would hide a deleted item from max(updated_at): deleting an item would no longer
    # move the order's updated_at, the watermark of mart_daily_sales.
    assert not drops_deleted_rows(block), f"{model} filters the rows of {staging}"


def test_fct_order_items_keeps_the_deleted_items_with_their_flag() -> None:
    # Canceled GMV is counted from them (D8): a filter here would zero it.
    sql = without_comments((MODELS / "marts" / f"{KEEPS_DELETED_ROWS}.sql").read_text())

    assert re.search(r"\bi\.is_deleted\b", sql), "fct_order_items does not expose is_deleted"
    assert not drops_deleted_rows(sql)


@pytest.mark.parametrize(
    "comment",
    [
        "-- where not is_deleted",
        "/* where not is_deleted */",
        "/* where\n   not is_deleted */",
        "{# where not is_deleted #}",
        "{# where\n   not is_deleted #}",
    ],
)
def test_a_comment_is_not_a_filter(comment: str) -> None:
    sql = f"select order_id\nfrom {{{{ ref('stg_orders') }}}}\n{comment}\n"

    assert not drops_deleted_rows(without_comments(sql))
    assert drops_deleted_rows(without_comments(sql + "where not is_deleted"))


@pytest.mark.parametrize(
    ("call", "guarded"),
    [
        ("arbitrary(price)", "arbitrary(case when not is_deleted then price end)"),
        ("array_agg(price)", "array_agg(case when not is_deleted then price end)"),
        ("approx_percentile(price, 0.5)", "approx_percentile(if(not is_deleted, price), 0.5)"),
        ("approx_distinct(price)", "approx_distinct(case when not is_deleted then price end)"),
        ("sum(price)", "sum(case when not is_deleted then price end)"),
        ("count(*)", "count_if(not is_deleted)"),
    ],
)
def test_aggregate_over_deleted_rows_is_unguarded_until_it_says_not_is_deleted(
    call: str, guarded: str
) -> None:
    assert unguarded_aggregates(f"select {call} from t") == [call]
    assert unguarded_aggregates(f"select {guarded} from t") == []
