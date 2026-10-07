"""The Iceberg streaming sink skips an epoch it already committed (ADR-007, chaos 1).

A crash between Iceberg's commit and Spark's own commit log makes Spark replay the batch. On the
live stack that window is milliseconds wide, so here it is reproduced by deleting the checkpoint's
commit entry by hand. The skip is keyed by query id, so a new checkpoint is the negative control.
"""

import os
import shutil
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


@needs_iceberg
def test_replayed_epoch_is_skipped(spark: SparkSession, tmp_path: Path) -> None:
    source, checkpoint = tmp_path / "in", tmp_path / "checkpoint"
    source.mkdir()
    spark.sql("create namespace if not exists lake.probe")
    spark.sql(f"create table {TABLE} (id bigint) using iceberg")

    def run(location: Path = checkpoint) -> None:
        (
            spark.readStream.schema("id bigint")
            .json(str(source))
            .writeStream.format("iceberg")
            .outputMode("append")
            .trigger(availableNow=True)
            .option("checkpointLocation", str(location))
            .toTable(TABLE)
            .awaitTermination()
        )

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
