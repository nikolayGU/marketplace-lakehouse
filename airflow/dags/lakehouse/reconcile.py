"""Reconciliation by value: source against silver, silver against gold (W5-T04, W5-D9), and the
GMV of every day, source against gold, independent of the dbt model (audit MODEL-02).

A row fingerprint is the md5 of the column values in one canonical text, built the same way in
Postgres and in Trino; a table fingerprint is the row count and the md5 of the sorted
`key=fingerprint` pairs. Only when two table fingerprints differ are the pairs pulled and compared
in Python (`diff_keys`), and `classify` says why a key is missing.

The canonical text of a value: `\\N` for null, so null and an empty string differ; the decimal at
its contract scale (ADR-020: the wire carries doubles, silver casts them); a timestamp as epoch
milliseconds (silver keeps milliseconds); everything else as text; values joined by chr(31).
No airflow import, so the tests run on the host. Table and column names come from the dictionaries
below, never from outside; the one value that goes into a query, a key to look up, is checked first.
"""

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

NULL = r"'\N'"
SAFE_KEY = re.compile(r"[A-Za-z0-9_.:\-]+")
DECIMAL = re.compile(r"decimal\(\s*\d+\s*,\s*(\d+)\s*\)")


@dataclass(frozen=True)
class Column:
    name: str
    silver_type: str
    gold_name: str = ""

    def __post_init__(self) -> None:
        if not self.gold_name:
            object.__setattr__(self, "gold_name", self.name)


@dataclass(frozen=True)
class Pair:
    """A gold table and the silver table it is built from. `live_only` leaves out soft-deleted
    silver rows; a gold table that keeps them (fct_order_items) carries the flag as a column."""

    silver_table: str
    keys: tuple[str, ...]
    columns: tuple[Column, ...]
    live_only: bool = True


def _cols(*specs: tuple[str, str]) -> tuple[Column, ...]:
    return tuple(Column(name, kind) for name, kind in specs)


# Keys and columns of silver, as contracts/silver/*.json declare them (test_reconcile.py compares).
TABLES: dict[str, tuple[tuple[str, ...], tuple[Column, ...]]] = {
    "customers": (
        ("customer_id",),
        _cols(
            ("customer_id", "string"),
            ("customer_unique_id", "string"),
            ("customer_zip_code_prefix", "string"),
            ("customer_city", "string"),
            ("customer_state", "string"),
        ),
    ),
    "order_items": (
        ("order_id", "order_item_id"),
        _cols(
            ("order_id", "string"),
            ("order_item_id", "int"),
            ("product_id", "string"),
            ("seller_id", "string"),
            ("shipping_limit_date", "timestamp_ntz"),
            ("price", "decimal(10,2)"),
            ("freight_value", "decimal(10,2)"),
        ),
    ),
    "orders": (
        ("order_id",),
        _cols(
            ("order_id", "string"),
            ("customer_id", "string"),
            ("order_status", "string"),
            ("order_purchase_timestamp", "timestamp_ntz"),
            ("order_approved_at", "timestamp_ntz"),
            ("order_delivered_carrier_date", "timestamp_ntz"),
            ("order_delivered_customer_date", "timestamp_ntz"),
            ("order_estimated_delivery_date", "timestamp_ntz"),
        ),
    ),
    "payments": (
        ("order_id", "payment_sequential"),
        _cols(
            ("order_id", "string"),
            ("payment_sequential", "int"),
            ("payment_type", "string"),
            ("payment_installments", "int"),
            ("payment_value", "decimal(10,2)"),
        ),
    ),
    "products": (
        ("product_id",),
        _cols(
            ("product_id", "string"),
            ("product_category_name", "string"),
            ("product_name_lenght", "int"),
            ("product_description_lenght", "int"),
            ("product_photos_qty", "int"),
            ("product_weight_g", "int"),
            ("product_length_cm", "int"),
            ("product_height_cm", "int"),
            ("product_width_cm", "int"),
        ),
    ),
    "reviews": (
        ("review_id", "order_id"),
        _cols(
            ("review_id", "string"),
            ("order_id", "string"),
            ("review_score", "int"),
            ("review_comment_title", "string"),
            ("review_comment_message", "string"),
            ("review_creation_date", "timestamp_ntz"),
            ("review_answer_timestamp", "timestamp_ntz"),
        ),
    ),
    "sellers": (
        ("seller_id",),
        _cols(
            ("seller_id", "string"),
            ("seller_zip_code_prefix", "string"),
            ("seller_city", "string"),
            ("seller_state", "string"),
        ),
    ),
}

_ORDERS = TABLES["orders"][1]
_ITEMS = TABLES["order_items"][1]
_PRODUCTS = TABLES["products"][1]
_SELLERS = TABLES["sellers"][1]

# Gold tables that carry silver's columns one to one. dim_customers has the grain
# customer_unique_id and the address of the latest order: only its row count is compared.
GOLD_PAIRS: dict[str, Pair] = {
    "fct_orders": Pair("orders", ("order_id",), _ORDERS[1:]),
    "fct_order_items": Pair(
        "order_items",
        ("order_id", "order_item_id"),
        (*_ITEMS[2:], Column("_is_deleted", "boolean", "is_deleted")),
        live_only=False,
    ),
    "dim_products": Pair(
        "products",
        ("product_id",),
        tuple(
            Column(c.name, c.silver_type, c.name.replace("lenght", "length")) for c in _PRODUCTS[1:]
        ),
    ),
    "dim_sellers": Pair("sellers", ("seller_id",), _SELLERS[1:]),
}

SILVER_CUSTOMERS_WITH_ORDERS = """
select count(distinct c.customer_unique_id)
from silver.orders o join silver.customers c on o.customer_id = c.customer_id
where not o._is_deleted and not c._is_deleted
"""
GOLD_CUSTOMERS = "select count(*) from gold.dim_customers"
# Gold has caught up when its newest row is not older than the newest silver row it is built from.
GOLD_UPDATED = "select cast(max(updated_at) as varchar) from gold.fct_orders"
# The mart has caught up with fct_orders when its watermark (the newest fct_orders.updated_at among
# the orders of a row) is not older than the newest fct_orders row. gold_at_rest compares them.
MART_UPDATED = "select cast(max(source_updated_at) as varchar) from gold.mart_daily_sales"
SILVER_UPDATED = """
select cast(max(u) as varchar) from (
    select max(_updated_at) as u from silver.orders
    union all select max(_updated_at) from silver.order_items
    union all select max(_updated_at) from silver.payments)
"""


def row_hash_sql_postgres(column: Column) -> str:
    """One column as canonical text, in Postgres."""
    name, kind = column.name, column.silver_type
    if kind == "timestamp_ntz":
        # floor, as Trino's date_diff and Debezium drop the sub-millisecond part
        value = f"(floor(extract(epoch from {name}) * 1000))::bigint::text"
    elif match := DECIMAL.fullmatch(kind):
        value = f"({name})::numeric(38, {match.group(1)})::text"
    else:
        value = f"({name})::text"
    return f"coalesce({value}, {NULL})"


def row_hash_sql_trino(column: Column, name: str | None = None) -> str:
    """One column as canonical text, in Trino. `name` is the column in the relation read."""
    name, kind = name or column.name, column.silver_type
    if kind == "timestamp_ntz":
        value = (
            f"cast(date_diff('millisecond', timestamp '1970-01-01 00:00:00', {name}) as varchar)"
        )
    elif match := DECIMAL.fullmatch(kind):
        value = f"cast(cast({name} as decimal(38, {match.group(1)})) as varchar)"
    else:
        value = f"cast({name} as varchar)"
    return f"coalesce({value}, {NULL})"


def _key(keys: Iterable[str], cast: str) -> str:
    parts = [f"cast({k} as varchar)" if cast == "trino" else f"{k}::text" for k in keys]
    return parts[0] if len(parts) == 1 else f"concat_ws(':', {', '.join(parts)})"


def _postgres(table: str) -> tuple[str, str, str]:
    keys, columns = TABLES[table]
    cells = ", ".join(row_hash_sql_postgres(c) for c in columns)
    rows = (
        f"select {_key(keys, 'pg')} as k, md5(concat_ws(chr(31), {cells})) as h from shop.{table}"
    )
    return rows, "k", "h"


def _fingerprint_postgres(rows: str) -> str:
    return (
        f"with r as ({rows}) select concat_ws(' ', count(*), "
        "md5(coalesce(string_agg(k || '=' || h, ',' order by k collate \"C\"), ''))) from r"
    )


def _pairs_postgres(rows: str) -> str:
    return f'with r as ({rows}) select k, h from r order by k collate "C"'


def fingerprint_sql_postgres(table: str) -> str:
    """`<rows> <md5>` of the source table."""
    rows, _, _ = _postgres(table)
    return _fingerprint_postgres(rows)


def pairs_sql_postgres(table: str) -> str:
    rows, _, _ = _postgres(table)
    return _pairs_postgres(rows)


def _trino(
    relation: str,
    keys: tuple[str, ...],
    columns: Iterable[tuple[Column, str]],
    where: str,
) -> str:
    cells = ", ".join(row_hash_sql_trino(c, name) for c, name in columns)
    hashed = f"lower(to_hex(md5(to_utf8(concat_ws(chr(31), {cells})))))"
    return f"select {_key(keys, 'trino')} as k, {hashed} as h from {relation}{where}"


def _silver_rows(
    table: str, live_only: bool = True, columns: Iterable[Column] | None = None
) -> str:
    keys, all_columns = TABLES[table]
    chosen = list(columns) if columns is not None else list(all_columns)
    where = " where not _is_deleted" if live_only else ""
    return _trino(f"silver.{table}", keys, [(c, c.name) for c in chosen], where)


def _fingerprint_trino(rows: str) -> str:
    return (
        f"with r as ({rows}) select concat_ws(' ', cast(count(*) as varchar), "
        "lower(to_hex(md5(to_utf8(coalesce(array_join(array_agg(k || '=' || h order by k), ','), "
        "'')))))) from r"
    )


def fingerprint_sql_trino(table: str) -> str:
    """`<rows> <md5>` of the live rows of a silver table."""
    return _fingerprint_trino(_silver_rows(table))


def pairs_sql_trino(table: str) -> str:
    return f"with r as ({_silver_rows(table)}) select k, h from r order by k"


def gold_silver_sql_trino(gold: str) -> str:
    """The silver side of a silver-gold pair, over the columns the gold table carries."""
    pair = GOLD_PAIRS[gold]
    return _fingerprint_trino(_silver_rows(pair.silver_table, pair.live_only, pair.columns))


def gold_sql_trino(gold: str) -> str:
    """The gold side of the pair: the same columns under the names the model gives them."""
    pair = GOLD_PAIRS[gold]
    rows = _trino(f"gold.{gold}", pair.keys, [(c, c.gold_name) for c in pair.columns], "")
    return _fingerprint_trino(rows)


def gold_pairs_sql_trino(gold: str, side: str) -> str:
    pair = GOLD_PAIRS[gold]
    if side == "silver":
        rows = _silver_rows(pair.silver_table, pair.live_only, pair.columns)
    else:
        rows = _trino(f"gold.{gold}", pair.keys, [(c, c.gold_name) for c in pair.columns], "")
    return f"with r as ({rows}) select k, h from r order by k"


# Orders whose items are not GMV. int_daily_sales.sql says the same (test_reconcile.py compares).
GMV_EXCLUDED_STATUSES = ("canceled", "unavailable")
GMV_TABLE = "mart_daily_sales_gmv"
_EXCLUDED = ", ".join(f"'{status}'" for status in GMV_EXCLUDED_STATUSES)
# The source deletes hard, so there is no soft-delete flag to filter. A day is `YYYY-MM-DD` and a
# sum is text at the scale of price (decimal(10,2)): the same text from both engines.
_GMV_POSTGRES = f"""
select to_char(o.order_purchase_timestamp, 'YYYY-MM-DD') as k,
    (sum(i.price))::numeric(38, 2)::text as h
from shop.order_items i join shop.orders o on o.order_id = i.order_id
where o.order_status not in ({_EXCLUDED})
group by 1
"""
# A day with only canceled or unavailable orders has a row in the mart with no live items: the
# source has no such day, so it is not an extra one.
_GMV_TRINO = """
select cast(purchase_date as varchar) as k, cast(cast(sum(gmv) as decimal(38, 2)) as varchar) as h
from gold.mart_daily_sales
group by purchase_date
having sum(items_count) > 0
"""


def gmv_fingerprint_sql_postgres() -> str:
    """`<days> <md5>` of `day=GMV` in the source, from order_items and orders."""
    return _fingerprint_postgres(_GMV_POSTGRES)


def gmv_pairs_sql_postgres() -> str:
    return _pairs_postgres(_GMV_POSTGRES)


def gmv_fingerprint_sql_trino() -> str:
    """`<days> <md5>` of `day=GMV` in gold.mart_daily_sales, summed over the seller states."""
    return _fingerprint_trino(_GMV_TRINO)


def gmv_pairs_sql_trino() -> str:
    return f"with r as ({_GMV_TRINO}) select k, h from r order by k"


def diff_keys(
    left: Mapping[str, str], right: Mapping[str, str]
) -> tuple[list[str], list[str], list[str]]:
    """(keys only on the left, keys only on the right, keys on both with different fingerprints)."""
    only_left = sorted(left.keys() - right.keys())
    only_right = sorted(right.keys() - left.keys())
    changed = sorted(k for k in left.keys() & right.keys() if left[k] != right[k])
    return only_left, only_right, changed


def classify(keys: Iterable[str], quarantined: set[str], in_bronze: set[str]) -> dict[str, str]:
    """Why a key the source has is not in silver: quarantined (silver refused the record),
    merge_pending (bronze has it, silver has not merged it yet), unknown (neither: look closer)."""
    reasons = {}
    for key in keys:
        if key in quarantined:
            reasons[key] = "quarantined"
        elif key in in_bronze:
            reasons[key] = "merge_pending"
        else:
            reasons[key] = "unknown"
    return reasons


def gold_at_rest(gold_updated: str | None, silver_updated: str | None) -> bool:
    """Gold is as new as silver. Both are timestamps as text, which sorts like the time."""
    if silver_updated is None:
        return True
    return gold_updated is not None and gold_updated >= silver_updated


def _lookup(relation: str, table: str, keys: list[str], where: str) -> str | None:
    """The first key column's value of each key found in `relation`; None when a key could put
    anything but a plain identifier into the query."""
    if table not in TABLES or not keys or not all(SAFE_KEY.fullmatch(k) for k in keys):
        return None
    first = TABLES[table][0][0]
    ids = ", ".join(f"'{k.split(':')[0]}'" for k in keys)
    return (
        f"select id from unnest(array[{ids}]) as t(id) where exists (select 1 from {relation} x "
        f"where {where.format(col=first)})"
    )


def bronze_lookup_sql(table: str, keys: list[str]) -> str | None:
    return _lookup(
        "lake.bronze.cdc_events",
        table,
        keys,
        f"x.source_table = '{table}' and strpos(coalesce(x.after, x.before), "
        "concat('\"{col}\":\"', t.id, '\"')) > 0",
    )


def quarantine_lookup_sql(table: str, keys: list[str]) -> str | None:
    return _lookup(
        "lake.silver.quarantine",
        table,
        keys,
        f"x.topic = 'oltp.shop.{table}' and "
        "strpos(x.payload, concat('\"{col}\":\"', t.id, '\"')) > 0",
    )


REPORTED_KEYS = 20


@dataclass
class Verdict:
    """The outcome for one table of one pair. `left` is the source (or silver, in a silver-gold
    pair) and `right` the layer compared with it."""

    pair: str
    table: str
    rows_left: int
    rows_right: int
    only_left: list[str] = field(default_factory=list)
    only_right: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        # The key pairs collapse into dicts: a duplicated key differs only in the row count.
        return self.rows_left == self.rows_right and not (
            self.only_left or self.only_right or self.changed
        )

    def summary(self) -> str:
        """The first keys of each kind of difference, with the reason for the missing ones."""
        lines = [f"{self.pair} {self.table}: rows {self.rows_left} against {self.rows_right}"]
        for label, keys in (
            ("missing on the right", self.only_left),
            ("missing on the left", self.only_right),
            ("different values", self.changed),
        ):
            for key in keys[:REPORTED_KEYS]:
                reason = self.reasons.get(key, "")
                lines.append(f"  {label}: {key}" + (f" ({reason})" if reason else ""))
        return "\n".join(lines)


def compare(
    pair: str,
    table: str,
    left_fingerprint: str,
    right_fingerprint: str,
    load_left: Callable[[], Mapping[str, str]],
    load_right: Callable[[], Mapping[str, str]],
    explain: Callable[[list[str]], dict[str, str]] | None = None,
) -> Verdict:
    """Compare two table fingerprints (`<rows> <md5>`). Equal: done, nothing is pulled. Different:
    pull the key=fingerprint pairs of this table only and say which keys differ and, for the keys
    the right side lacks, why (`explain`)."""
    rows_left, rows_right = int(left_fingerprint.split()[0]), int(right_fingerprint.split()[0])
    verdict = Verdict(pair, table, rows_left, rows_right)
    if left_fingerprint == right_fingerprint:
        return verdict
    verdict.only_left, verdict.only_right, verdict.changed = diff_keys(load_left(), load_right())
    if explain is not None and verdict.only_left:
        verdict.reasons = explain(verdict.only_left)
    return verdict
