import calendar
import json
import os
import shutil
from collections.abc import Callable, Iterator
from datetime import datetime
from glob import glob
from pathlib import Path
from typing import Any

import pytest
from pyspark.sql import DataFrame, SparkSession
from spark_jobs.orders_per_minute import (
    describe,
    ensure_table,
    parse_orders,
    upsert,
    windowed_counts,
)

HAS_JAVA = shutil.which("java") is not None
SPARK_JARS = f"{os.environ.get('SPARK_HOME', '/opt/spark')}/jars"
HAS_ICEBERG = bool(glob(f"{SPARK_JARS}/iceberg-spark-runtime-*"))
needs_java = pytest.mark.skipif(not HAS_JAVA, reason="local SparkSession needs a JVM")
needs_iceberg = pytest.mark.skipif(
    not (HAS_JAVA and HAS_ICEBERG), reason="needs the Iceberg runtime jar: run `make test-spark`"
)

Window = dict[str, int]


@pytest.fixture(scope="module")
def spark(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SparkSession]:
    builder = (
        SparkSession.builder.master("local[2]")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.sql.session.timeZone", "UTC")
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
            .config("spark.sql.catalog.lake.cache-enabled", "false")
        )
    session = builder.getOrCreate()
    yield session
    session.stop()


def ms(hour: int, minute: int, second: int) -> int:
    # calendar.timegm: the image runs Python 3.10, which has no datetime.UTC.
    return calendar.timegm((2026, 7, 1, hour, minute, second)) * 1000


def envelope(order_id: str, purchase_ms: int | None, op: str = "c") -> str:
    return json.dumps(
        {
            "op": op,
            "ts_ms": 1790104945151,
            "before": None,
            "after": {"order_id": order_id, "order_purchase_timestamp": purchase_ms},
            "source": {"lsn": 1, "sequence": None, "ts_ms": 1790104944721, "table": "orders"},
        }
    )


def window_label(start: datetime) -> str:
    return start.strftime("%H:%M")


def run_batches(
    spark: SparkSession,
    tmp_path: Path,
    batches: list[list[str]],
    sink: Callable[[DataFrame, int], None] | None = None,
) -> tuple[dict[int, Window], list[dict[str, Any]]]:
    """Each element of `batches` is one file, read as one micro-batch (maxFilesPerTrigger=1, files
    ordered by mtime). Returns, per batch id, the windows the aggregation emitted, and the
    progress dicts of the run."""
    source = tmp_path / "source"
    source.mkdir()
    for number, lines in enumerate(batches):
        path = source / f"{number:03d}.json"
        path.write_text("\n".join(lines) + "\n")
        os.utime(path, (1_700_000_000 + number * 60, 1_700_000_000 + number * 60))

    emitted: dict[int, Window] = {}

    def collect(batch: DataFrame, batch_id: int) -> None:
        emitted[batch_id] = {
            window_label(row["window_start"]): row["orders"] for row in batch.collect()
        }

    events = parse_orders(
        spark.readStream.format("text").option("maxFilesPerTrigger", 1).load(str(source))
    )
    query = (
        windowed_counts(events, "5 minutes")
        .writeStream.outputMode("update")
        .foreachBatch(sink or collect)
        .option("checkpointLocation", str(tmp_path / "checkpoint"))
        .trigger(availableNow=True)
        .start()
    )
    query.awaitTermination()
    return emitted, list(query.recentProgress)


FIRST = [
    envelope("a", ms(10, 0, 10)),
    envelope("b", ms(10, 4, 30)),
    envelope("c", ms(10, 10, 20)),
]


@needs_java
def test_an_event_inside_the_watermark_opens_its_window(
    spark: SparkSession, tmp_path: Path
) -> None:
    # After batch 1 the watermark is 10:10:20 - 5 min = 10:05:20; window 10:07 ends at 10:08.
    emitted, _ = run_batches(spark, tmp_path, [FIRST, [envelope("d", ms(10, 7, 40))]])

    assert emitted[0] == {"10:00": 1, "10:04": 1, "10:10": 1}
    assert emitted[1] == {"10:07": 1}


@needs_java
def test_an_event_behind_the_watermark_is_dropped_and_counted(
    spark: SparkSession, tmp_path: Path
) -> None:
    # Window 10:04 closed at 10:05, before the watermark of 10:05:20. Spark drops a late row
    # against the watermark of the previous batch, so the event goes into the third batch.
    inside = [envelope("d", ms(10, 7, 40))]
    late = [envelope("e", ms(10, 4, 50))]
    emitted, progress = run_batches(spark, tmp_path, [FIRST, inside, late])

    assert emitted[1] == {"10:07": 1}
    assert "10:04" not in emitted.get(2, {})
    assert progress[-1]["stateOperators"][0]["numRowsDroppedByWatermark"] >= 1


@needs_java
def test_the_first_batch_after_the_watermark_moves_still_takes_a_late_event(
    spark: SparkSession, tmp_path: Path
) -> None:
    # The same event one batch earlier is counted: the watermark that drops rows is the one the
    # previous batch ran with (0 here), the new one only evicts state afterwards. This is the
    # grace of one batch, and why the demo needs one run per batch.
    late = [envelope("d", ms(10, 7, 40)), envelope("e", ms(10, 4, 50))]
    emitted, _ = run_batches(spark, tmp_path, [FIRST, late])

    assert emitted[1] == {"10:07": 1, "10:04": 2}


@needs_java
def test_the_same_order_twice_in_a_window_counts_once(spark: SparkSession, tmp_path: Path) -> None:
    # Debezium resends after a Connect kill (chaos 2b): a count(*) would say 2.
    emitted, _ = run_batches(spark, tmp_path, [FIRST, [envelope("c", ms(10, 10, 20))]])

    assert emitted[0]["10:10"] == 1
    assert emitted.get(1, {}).get("10:10", 1) == 1


@needs_java
def test_what_is_not_a_new_order_with_a_sane_time_is_ignored(
    spark: SparkSession, tmp_path: Path
) -> None:
    junk = [
        "not json at all",
        envelope("u1", ms(10, 1, 0), op="u"),
        envelope("r1", ms(10, 1, 0), op="r"),
        envelope("", ms(10, 1, 0)),
        envelope("nulltime", None),
        envelope("far-future", 253402300800000),
        envelope("before-year-1", -62135596800001),
        envelope("ok", ms(10, 1, 5)),
    ]
    emitted, _ = run_batches(spark, tmp_path, [junk])

    assert emitted[0] == {"10:01": 1}


@needs_java
def test_state_rows_after_batch_two_are_the_open_windows(
    spark: SparkSession, tmp_path: Path
) -> None:
    _, progress = run_batches(spark, tmp_path, [FIRST, [envelope("d", ms(10, 7, 40))]])

    # Windows 10:00 and 10:04 are behind the watermark and evicted; 10:07 and 10:10 remain.
    assert progress[-1]["stateOperators"][0]["numRowsTotal"] == 2


@needs_java
def test_describe_prints_one_line_with_watermark_and_state(
    spark: SparkSession, tmp_path: Path
) -> None:
    _, progress = run_batches(spark, tmp_path, [FIRST, [envelope("d", ms(10, 7, 40))]])

    line = describe(progress[-1])

    assert line.startswith("progress batch=")
    # Batch 1 ran with the watermark batch 0 left behind: 10:10:20 minus five minutes.
    assert "watermark=2026-07-01T10:05:20" in line
    assert "state_rows=" in line and "dropped=" in line and "input_rows=" in line


def make_batch(spark: SparkSession, rows: list[tuple[str, int]]) -> DataFrame:
    return spark.createDataFrame(rows, "window_start string, orders long").selectExpr(
        "cast(window_start as timestamp_ntz) as window_start", "orders"
    )


@needs_iceberg
def test_upsert_twice_with_the_same_batch_changes_nothing(spark: SparkSession) -> None:
    target = "lake.silver.opm_idempotent"
    spark.sql("create namespace if not exists lake.silver")
    ensure_table(spark, target)
    batch = make_batch(spark, [("2026-07-01 10:00:00", 2), ("2026-07-01 10:01:00", 1)])

    upsert(batch, 0, target)
    first = spark.table(target).orderBy("window_start").collect()
    upsert(batch, 0, target)

    assert [(r["window_start"], r["orders"]) for r in spark.table(target).collect()] == [
        (r["window_start"], r["orders"]) for r in first
    ]
    assert spark.table(target).count() == 2


@needs_iceberg
def test_upsert_never_lowers_a_count(spark: SparkSession) -> None:
    target = "lake.silver.opm_monotonic"
    spark.sql("create namespace if not exists lake.silver")
    ensure_table(spark, target)

    upsert(make_batch(spark, [("2026-07-01 10:00:00", 5)]), 0, target)
    upsert(make_batch(spark, [("2026-07-01 10:00:00", 3)]), 1, target)
    upsert(make_batch(spark, [("2026-07-01 10:00:00", 7)]), 2, target)

    assert [r["orders"] for r in spark.table(target).collect()] == [7]


@needs_iceberg
def test_upsert_runs_the_stateful_batch_once(spark: SparkSession, tmp_path: Path) -> None:
    # An action on the batch frame re-runs the aggregation. On the Kafka source of the first live
    # demo, unpersisted, one late event was counted as dropped 3 times (state_rows 8 for 3 windows);
    # a local file source does not reproduce it, so this pins the exact numbers rather than
    # proving the persist.
    target = "lake.silver.opm_once"
    spark.sql("create namespace if not exists lake.silver")
    ensure_table(spark, target)
    inside = [envelope("d", ms(10, 7, 40))]
    late = [envelope("e", ms(10, 4, 50))]

    _, progress = run_batches(
        spark, tmp_path, [FIRST, inside, late], sink=lambda b, i: upsert(b, i, target)
    )

    state = progress[-1]["stateOperators"][0]
    assert state["numRowsDroppedByWatermark"] == 1
    assert state["numRowsTotal"] == 2
