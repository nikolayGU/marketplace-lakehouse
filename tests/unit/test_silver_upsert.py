import json
import os
import shutil
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from glob import glob
from pathlib import Path
from typing import Any

import pytest
from pyspark.sql import DataFrame, Row, SparkSession
from spark_jobs.bronze_cdc_ingest import DDL as BRONZE_DDL
from spark_jobs.contracts import TableContract, load_contracts
from spark_jobs.silver_upsert import (
    BRONZE,
    SILVER,
    ensure_table,
    latest_per_key,
    merge_batch,
    row_images,
    run,
    valid,
)

CONTRACTS = load_contracts(Path(__file__).parents[2] / "contracts" / "silver")
BRONZE_NAMESPACE = BRONZE.rsplit(".", 1)[0]
ORDERS = CONTRACTS["orders"]
BRONZE_COLUMNS = (
    "topic string, kafka_partition int, kafka_offset bigint, kafka_ts timestamp, key string, "
    "op string, lsn bigint, ts_ms bigint, source_ts_ms bigint, source_table string, "
    "before string, after string, raw string, ingest_ts timestamp"
)

HAS_JAVA = shutil.which("java") is not None
SPARK_JARS = f"{os.environ.get('SPARK_HOME', '/opt/spark')}/jars"
HAS_ICEBERG = bool(glob(f"{SPARK_JARS}/iceberg-spark-runtime-*"))
needs_java = pytest.mark.skipif(not HAS_JAVA, reason="local SparkSession needs a JVM")
needs_iceberg = pytest.mark.skipif(
    not (HAS_JAVA and HAS_ICEBERG), reason="needs the Iceberg runtime jar: run `make test-spark`"
)


@pytest.fixture(scope="module")
def spark(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SparkSession]:
    builder = (
        SparkSession.builder.master("local[2]")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "2")
    )
    if HAS_ICEBERG:
        warehouse = tmp_path_factory.mktemp("warehouse")
        builder = (
            builder.config(
                "spark.sql.extensions",
                "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
            )
            .config("spark.sql.catalog.lake", "org.apache.iceberg.spark.SparkCatalog")
            .config("spark.sql.catalog.lake.type", "hadoop")
            .config("spark.sql.catalog.lake.warehouse", f"file://{warehouse}")
            # foreachBatch runs in a cloned session with its own catalog; with caching on, this
            # session would not see the MERGE commits for 30 s.
            .config("spark.sql.catalog.lake.cache-enabled", "false")
        )
    session = builder.getOrCreate()
    yield session
    session.stop()


def order(order_id: str = "o1", status: str = "created", **extra: Any) -> dict[str, Any]:
    row = {
        "order_id": order_id,
        "customer_id": "c1",
        "order_status": status,
        "order_purchase_timestamp": 1782111448898,
        "order_approved_at": None,
        "order_delivered_carrier_date": None,
        "order_delivered_customer_date": None,
        "order_estimated_delivery_date": 1782777861898,
    }
    row.update(extra)
    return row


_offset = iter(range(1_000_000))


def event(
    op: str | None,
    after: dict[str, Any] | None = None,
    before: dict[str, Any] | None = None,
    lsn: int | None = 100,
    ts_ms: int = 1_790_000_000_000,
    table: str = "orders",
    raw: str | None = None,
) -> Row:
    return Row(
        topic=f"oltp.shop.{table}",
        kafka_partition=0,
        kafka_offset=next(_offset),
        kafka_ts=datetime(2026, 9, 23, 12, 0),
        key=None,
        op=op,
        lsn=lsn,
        ts_ms=ts_ms,
        source_ts_ms=ts_ms,
        source_table=table,
        before=json.dumps(before) if before is not None else None,
        after=json.dumps(after) if after is not None else None,
        raw=raw,
        ingest_ts=datetime(2026, 9, 23, 12, 0, 1),
    )


def bronze(spark: SparkSession, *events: Row) -> DataFrame:
    return spark.createDataFrame(list(events), BRONZE_COLUMNS)


def latest(spark: SparkSession, *events: Row, contract: TableContract = ORDERS) -> list[Row]:
    images = row_images(bronze(spark, *events), contract)
    rows = latest_per_key(images.where(valid(contract)), contract).collect()
    return sorted(rows, key=lambda r: tuple(r[k] for k in contract.primary_key))


@needs_java
def test_highest_lsn_wins_whatever_the_arrival_order(spark: SparkSession) -> None:
    [row] = latest(
        spark,
        event("u", order(status="shipped"), order(), lsn=300),
        event("c", order(), lsn=100),
        event("u", order(status="approved"), order(), lsn=200),
    )

    assert (row.order_status, row._last_lsn, row._is_deleted) == ("shipped", 300, False)
    assert row.order_purchase_timestamp == datetime(2026, 6, 22, 6, 57, 28, 898000)
    assert row._updated_at is not None


@needs_java
def test_exact_duplicates_collapse_to_one_row(spark: SparkSession) -> None:
    rows = latest(spark, event("c", order(), lsn=100), event("c", order(), lsn=100))

    assert len(rows) == 1


@needs_java
def test_streamed_change_beats_an_incremental_snapshot_read(spark: SparkSession) -> None:
    [row] = latest(
        spark,
        event("u", order(status="approved"), order(), lsn=200, ts_ms=1_000),
        event("r", order(status="created"), lsn=None, ts_ms=9_000),
    )

    assert (row.order_status, row._last_lsn) == ("approved", 200)


@needs_java
def test_later_snapshot_read_beats_an_earlier_one(spark: SparkSession) -> None:
    [row] = latest(
        spark,
        event("r", order(status="shipped"), lsn=None, ts_ms=2_000),
        event("r", order(status="approved"), lsn=None, ts_ms=1_000),
    )

    assert (row.order_status, row._last_lsn) == ("shipped", None)


@needs_java
def test_delete_reads_the_row_from_before(spark: SparkSession) -> None:
    [row] = latest(spark, event("d", before=order(status="canceled"), lsn=500))

    assert (row.order_id, row.order_status, row._is_deleted) == ("o1", "canceled", True)


@needs_java
def test_composite_keys_are_kept_apart(spark: SparkSession) -> None:
    item = {
        "order_id": "o1",
        "product_id": "p1",
        "seller_id": "s1",
        "shipping_limit_date": 1782670471898,
        "price": 99.9,
        "freight_value": 39.98,
    }
    rows = latest(
        spark,
        event("c", item | {"order_item_id": 1}, table="order_items", lsn=10),
        event("c", item | {"order_item_id": 2, "price": 10.0}, table="order_items", lsn=11),
        contract=CONTRACTS["order_items"],
    )

    assert [(r.order_item_id, r.price) for r in rows] == [
        (1, Decimal("99.90")),
        (2, Decimal("10.00")),
    ]


@needs_java
@pytest.mark.parametrize(
    "bad",
    [
        event(None, raw="not json at all {"),
        event("c", after=None),
        event("c", after={"order_status": "created"}),
        event("c", order(order_purchase_timestamp="yesterday")),
        event("c", order(order_estimated_delivery_date=None)),
        event("t", order()),
    ],
    ids=["unparsed-envelope", "no-payload", "no-key", "wrong-type", "null-required", "truncate"],
)
def test_invalid_event_is_not_merged(spark: SparkSession, bad: Row) -> None:
    rows = latest(spark, bad, event("c", order("o2"), lsn=100))

    assert [r.order_id for r in rows] == ["o2"]


@needs_java
def test_delete_with_only_the_key_in_before_is_valid(spark: SparkSession) -> None:
    [row] = latest(spark, event("d", before={"order_id": "o1"}, lsn=500))

    assert (row.order_id, row._is_deleted, row.customer_id) == ("o1", True, None)


# Iceberg: MERGE semantics and the AvailableNow run, against a local Hadoop catalog.


def silver(spark: SparkSession, table: str = "orders") -> dict[str, Row]:
    return {r.order_id: r for r in spark.table(f"{SILVER}.{table}").collect()}


@pytest.fixture
def fresh_silver(spark: SparkSession) -> Iterator[None]:
    spark.sql(f"create namespace if not exists {SILVER}")
    for contract in CONTRACTS.values():
        spark.sql(f"drop table if exists {SILVER}.{contract.table}")
        ensure_table(spark, contract)
    yield


@needs_iceberg
@pytest.mark.usefixtures("fresh_silver")
def test_replaying_a_batch_changes_nothing(spark: SparkSession) -> None:
    batch = bronze(spark, event("c", order(), lsn=100), event("c", order("o2"), lsn=110))

    merge_batch(batch, 0, CONTRACTS)
    first = silver(spark)
    merge_batch(batch, 0, CONTRACTS)

    assert silver(spark).keys() == first.keys() == {"o1", "o2"}
    assert {k: r._last_lsn for k, r in silver(spark).items()} == {"o1": 100, "o2": 110}


@needs_iceberg
@pytest.mark.usefixtures("fresh_silver")
def test_late_event_does_not_roll_a_row_back(spark: SparkSession) -> None:
    merge_batch(bronze(spark, event("u", order(status="delivered"), lsn=400)), 0, CONTRACTS)
    merge_batch(bronze(spark, event("u", order(status="shipped"), lsn=300)), 1, CONTRACTS)

    assert silver(spark)["o1"].order_status == "delivered"


@needs_iceberg
@pytest.mark.usefixtures("fresh_silver")
def test_delete_is_soft_and_a_resent_insert_does_not_resurrect(spark: SparkSession) -> None:
    merge_batch(bronze(spark, event("c", order(), lsn=100)), 0, CONTRACTS)
    merge_batch(bronze(spark, event("d", before={"order_id": "o1"}, lsn=200)), 1, CONTRACTS)
    merge_batch(bronze(spark, event("c", order(), lsn=100)), 2, CONTRACTS)

    row = silver(spark)["o1"]
    assert (row._is_deleted, row._last_lsn) == (True, 200)
    # The delete only flags the row: the key-only `before` did not blank the other columns.
    assert (row.customer_id, row.order_status) == ("c1", "created")


@needs_iceberg
@pytest.mark.usefixtures("fresh_silver")
def test_insert_after_delete_brings_the_row_back(spark: SparkSession) -> None:
    merge_batch(bronze(spark, event("d", before=order(), lsn=200)), 0, CONTRACTS)
    merge_batch(bronze(spark, event("c", order(status="approved"), lsn=300)), 1, CONTRACTS)

    row = silver(spark)["o1"]
    assert (row._is_deleted, row.order_status) == (False, "approved")


@needs_iceberg
@pytest.mark.usefixtures("fresh_silver")
def test_snapshot_read_fills_gaps_but_never_overwrites_a_streamed_row(spark: SparkSession) -> None:
    merge_batch(bronze(spark, event("u", order(status="shipped"), lsn=300)), 0, CONTRACTS)
    merge_batch(
        bronze(
            spark,
            event("r", order(status="created"), lsn=None),
            event("r", order("o2", status="delivered"), lsn=None),
        ),
        1,
        CONTRACTS,
    )
    merge_batch(bronze(spark, event("u", order("o2", status="canceled"), lsn=500)), 2, CONTRACTS)

    rows = silver(spark)
    assert (rows["o1"].order_status, rows["o1"]._last_lsn) == ("shipped", 300)
    assert (rows["o2"].order_status, rows["o2"]._last_lsn) == ("canceled", 500)


@needs_iceberg
@pytest.mark.usefixtures("fresh_silver")
def test_table_that_drifted_from_its_contract_stops_the_job(spark: SparkSession) -> None:
    spark.sql(f"alter table {SILVER}.orders add column sales_channel string")

    with pytest.raises(RuntimeError, match=r"unexpected .*sales_channel"):
        ensure_table(spark, ORDERS)


@needs_iceberg
@pytest.mark.usefixtures("fresh_silver")
def test_run_processes_only_what_bronze_committed_since_the_last_run(
    spark: SparkSession, tmp_path: Path
) -> None:
    spark.sql(f"create namespace if not exists {BRONZE_NAMESPACE}")
    spark.sql(f"drop table if exists {BRONZE}")
    spark.sql(BRONZE_DDL)
    checkpoint = f"file://{tmp_path}/checkpoint"

    bronze(spark, event("c", order(), lsn=100), event("c", order("o2"), lsn=110)).writeTo(
        BRONZE
    ).append()
    bronze(spark, event("u", order(status="approved"), lsn=120)).writeTo(BRONZE).append()
    run(spark, CONTRACTS, checkpoint, max_rows_per_batch=1)
    first = silver(spark)

    bronze(spark, event("d", before=order("o2"), lsn=130)).writeTo(BRONZE).append()
    run(spark, CONTRACTS, checkpoint, max_rows_per_batch=1)
    second = silver(spark)

    assert first["o1"].order_status == "approved"
    assert (first["o2"]._is_deleted, second["o2"]._is_deleted) == (False, True)
    # o1 got no new event, so the second run left its row alone.
    assert second["o1"]._updated_at == first["o1"]._updated_at
