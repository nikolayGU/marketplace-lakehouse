"""The Iceberg streaming sink skips an epoch it already committed (ADR-007, chaos 1).

A crash between Iceberg's commit and Spark's own commit log makes Spark replay the batch. On the
live stack that window is milliseconds wide, so here it is reproduced by deleting the checkpoint's
commit entry by hand. The skip is keyed by query id, so a new checkpoint is the negative control,
and two queries that append to one table, a stream and its replacement on a new checkpoint, each
keep their own epochs and each skips only a replay of its own.
"""

import os
import shutil
from collections import defaultdict
from collections.abc import Iterator
from glob import glob
from pathlib import Path

import pytest
from pyspark.sql import SparkSession

HAS_JAVA = shutil.which("java") is not None
SPARK_JARS = f"{os.environ.get('SPARK_HOME', '/opt/spark')}/jars"
HAS_ICEBERG = bool(glob(f"{SPARK_JARS}/iceberg-spark-runtime-*"))
needs_iceberg = pytest.mark.skipif(
    not (HAS_JAVA and HAS_ICEBERG), reason="needs the Iceberg runtime jar: run `make test-spark`"
)
TABLE = "lake.probe.sink"


@pytest.fixture(scope="module")
def spark(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SparkSession]:
    warehouse = tmp_path_factory.mktemp("warehouse")
    session = (
        SparkSession.builder.master("local[2]")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "2")
        .config(
            "spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        )
        .config("spark.sql.catalog.lake", "org.apache.iceberg.spark.SparkCatalog")
        .config("spark.sql.catalog.lake.type", "hadoop")
        .config("spark.sql.catalog.lake.warehouse", f"file://{warehouse}")
        .config("spark.sql.catalog.lake.cache-enabled", "false")
        .getOrCreate()
    )
    yield session
    session.stop()


def epochs(spark: SparkSession) -> list[str]:
    return [
        r.epoch
        for r in spark.sql(
            f"select summary['spark.sql.streaming.epochId'] as epoch from {TABLE}.snapshots "
            "order by committed_at"
        ).collect()
    ]


def drain(spark: SparkSession, source: Path, checkpoint: Path, table: str) -> None:
    (
        spark.readStream.schema("id bigint")
        .json(str(source))
        .writeStream.format("iceberg")
        .outputMode("append")
        .trigger(availableNow=True)
        .option("checkpointLocation", str(checkpoint))
        .toTable(table)
        .awaitTermination()
    )


def ids(spark: SparkSession, table: str) -> list[int]:
    return sorted(r.id for r in spark.table(table).collect())


def commits(spark: SparkSession, table: str) -> list[tuple[str, str]]:
    """(query id, epoch id) in each snapshot summary, oldest first."""
    return [
        (r.query, r.epoch)
        for r in spark.sql(
            "select summary['spark.sql.streaming.queryId'] as query, "
            f"summary['spark.sql.streaming.epochId'] as epoch from {table}.snapshots "
            "order by committed_at"
        ).collect()
    ]


def epochs_by_query(spark: SparkSession, table: str) -> dict[str, list[str]]:
    by_query: dict[str, list[str]] = defaultdict(list)
    for query, epoch in commits(spark, table):
        by_query[query].append(epoch)
    return dict(by_query)


class Query:
    """A query with its own source directory and checkpoint, appending to a shared table."""

    def __init__(self, spark: SparkSession, root: Path, table: str) -> None:
        self.spark, self.table = spark, table
        self.source, self.checkpoint = root / "in", root / "checkpoint"
        self.source.mkdir(parents=True)
        self.files = 0

    def append(self, row_id: int) -> None:
        """One new file and one run: one micro batch, the next epoch of this query."""
        self.files += 1
        (self.source / f"{self.files}.json").write_text(f'{{"id": {row_id}}}\n')
        self.run()

    def run(self) -> None:
        drain(self.spark, self.source, self.checkpoint, self.table)

    def forget_commit(self, epoch: int) -> None:
        """Iceberg holds the epoch, Spark's commit log does not: the state a kill leaves."""
        for name in (str(epoch), f".{epoch}.crc"):
            (self.checkpoint / "commits" / name).unlink(missing_ok=True)
        assert not (self.checkpoint / "commits" / str(epoch)).exists()


def shared_table(spark: SparkSession, tmp_path: Path, name: str) -> tuple[str, Query, Query]:
    table = f"lake.probe.{name}"
    spark.sql("create namespace if not exists lake.probe")
    spark.sql(f"create table {table} (id bigint) using iceberg")
    return table, Query(spark, tmp_path / "first", table), Query(spark, tmp_path / "second", table)


@needs_iceberg
def test_replayed_epoch_is_skipped(spark: SparkSession, tmp_path: Path) -> None:
    source, checkpoint = tmp_path / "in", tmp_path / "checkpoint"
    source.mkdir()
    spark.sql("create namespace if not exists lake.probe")
    spark.sql(f"create table {TABLE} (id bigint) using iceberg")

    def run(location: Path = checkpoint) -> None:
        drain(spark, source, location, TABLE)

    (source / "1.json").write_text('{"id": 1}\n')
    run()
    (source / "2.json").write_text('{"id": 2}\n')
    run()
    assert epochs(spark) == ["0", "1"]

    # Iceberg holds epoch 1, Spark's commit log does not: the state a kill leaves in the window.
    commit = checkpoint / "commits" / "1"
    for entry in (checkpoint / "commits").glob("*1*"):  # "1" and its ".1.crc"
        entry.unlink()
    assert not commit.exists()
    run()
    assert commit.exists()  # Spark re-ran batch 1 ...
    assert sorted(r.id for r in spark.table(TABLE).collect()) == [1, 2]
    assert epochs(spark) == ["0", "1"]  # ... and Iceberg added no rows and no snapshot for it
    (source / "3.json").write_text('{"id": 3}\n')
    run()

    assert sorted(r.id for r in spark.table(TABLE).collect()) == [1, 2, 3]
    assert epochs(spark) == ["0", "1", "2"]

    # A new checkpoint is a new query id: Iceberg finds no epoch of its own and appends again.
    run(tmp_path / "checkpoint-new")
    assert sorted(r.id for r in spark.table(TABLE).collect()) == [1, 1, 2, 2, 3, 3]
    assert epochs(spark).count("0") == 2


@needs_iceberg
def test_second_query_writes_its_own_epochs_into_a_table_the_first_already_wrote(
    spark: SparkSession, tmp_path: Path
) -> None:
    table, first, second = shared_table(spark, tmp_path, "second_query")
    first.append(1)
    first.append(2)
    assert [epoch for _, epoch in commits(spark, table)] == ["0", "1"]

    # The table holds epochs 0 and 1 of another query: the second one starts at 0 all the same.
    second.append(10)
    second.append(20)

    assert ids(spark, table) == [1, 2, 10, 20]
    by_query = epochs_by_query(spark, table)
    assert len(by_query) == 2, f"one query id for two queries: {by_query}"
    assert sorted(by_query.values()) == [["0", "1"], ["0", "1"]]


@needs_iceberg
def test_replayed_epoch_of_either_query_is_skipped_and_the_other_one_is_untouched(
    spark: SparkSession, tmp_path: Path
) -> None:
    table, first, second = shared_table(spark, tmp_path, "replay_two_queries")
    # Interleaved, so the newest snapshot of the table is the second query's and the first
    # query's newest epoch lies behind it.
    first.append(1)
    second.append(10)
    first.append(2)
    second.append(20)
    written = commits(spark, table)
    assert [epoch for _, epoch in written] == ["0", "0", "1", "1"]
    assert ids(spark, table) == [1, 2, 10, 20]

    for query, epoch in ((second, 1), (first, 1)):
        query.forget_commit(epoch)
        query.run()

        assert (query.checkpoint / "commits" / str(epoch)).exists()  # Spark re-ran the batch ...
        assert ids(spark, table) == [1, 2, 10, 20]  # ... Iceberg added no rows ...
        assert commits(spark, table) == written  # ... and no snapshot, for either query

    # Neither skip moved on: each query's next epoch is written.
    first.append(3)
    second.append(30)

    assert ids(spark, table) == [1, 2, 3, 10, 20, 30]
    assert sorted(epochs_by_query(spark, table).values()) == [["0", "1", "2"], ["0", "1", "2"]]
