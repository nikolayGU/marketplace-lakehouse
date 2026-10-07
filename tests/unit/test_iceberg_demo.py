"""`make iceberg-demo` runs end to end on a local catalog and leaves the sandbox compacted."""

import os
import shutil
from collections.abc import Iterator
from glob import glob
from pathlib import Path

import pytest
from pyspark.sql import SparkSession
from spark_jobs import iceberg_demo
from spark_jobs.catalog import CATALOG
from spark_jobs.contracts import load_contracts
from spark_jobs.iceberg_demo import DEMO, show, walkthrough
from spark_jobs.silver_upsert import SILVER, ensure_table

HAS_JAVA = shutil.which("java") is not None
SPARK_JARS = f"{os.environ.get('SPARK_HOME', '/opt/spark')}/jars"
HAS_ICEBERG = bool(glob(f"{SPARK_JARS}/iceberg-spark-runtime-*"))
needs_iceberg = pytest.mark.skipif(
    not (HAS_JAVA and HAS_ICEBERG), reason="needs the Iceberg runtime jar: run `make test-spark`"
)


@pytest.fixture(scope="module")
def spark(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SparkSession]:
    warehouse = tmp_path_factory.mktemp("warehouse")
    session = (
        SparkSession.builder.master("local[2]")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.sql.session.timeZone", "UTC")
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


def first_cell(section: str) -> str:
    """The first value under the header of the table `show()` printed in a transcript section."""
    rows = [line for line in section.splitlines() if line.startswith("|")]
    return rows[1].strip("|").split("|")[0].strip()


def root_log_level(spark: SparkSession) -> str:
    jvm = spark.sparkContext._jvm
    assert jvm is not None
    return str(jvm.org.apache.logging.log4j.LogManager.getRootLogger().getLevel())


@needs_iceberg
def test_main_keeps_spark_info_logs_out_of_the_transcript(
    spark: SparkSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # From a terminal `docker compose run` gets a TTY, which merges Spark's stderr log into the
    # transcript: `2>/dev/null` cannot hide it, so the job has to be quiet itself.
    levels: list[str] = []
    monkeypatch.setattr(iceberg_demo, "Settings", lambda: None)
    monkeypatch.setattr(iceberg_demo, "build_session", lambda *_: spark)
    monkeypatch.setattr(iceberg_demo, "walkthrough", lambda s: levels.append(root_log_level(s)))
    monkeypatch.setattr(spark, "stop", lambda: None)

    try:
        iceberg_demo.main()
    finally:
        # pyspark starts with an INFO root logger behind a WARN console filter, and setLogLevel
        # drops that filter: restoring INFO would print Spark's INFO log for every later test.
        spark.sparkContext.setLogLevel("WARN")

    assert levels == ["WARN"]


@needs_iceberg
def test_show_prints_past_sparks_default_of_20_rows(
    spark: SparkSession, capsys: pytest.CaptureFixture[str]
) -> None:
    show(spark, "25 rows", "select concat('row-', id) as r from range(25)")

    assert "row-24" in capsys.readouterr().out


@needs_iceberg
def test_walkthrough_ends_compacted_with_one_snapshot(
    spark: SparkSession, capsys: pytest.CaptureFixture[str]
) -> None:
    contracts = load_contracts(Path(__file__).parents[2] / "contracts" / "silver")
    spark.sql(f"create namespace if not exists {SILVER}")
    ensure_table(spark, contracts["orders"])
    # One commit per month, like the live monthly table: several files and manifests, so a slice
    # taken without a total order can differ from one query to the next.
    for month in range(3, 7):
        spark.sql(
            f"insert into {SILVER}.orders select concat('o', id), 'c1', "
            "case when id % 2 = 0 then 'delivered' else 'shipped' end, "
            f"timestamp_ntz'2026-0{month}-01 10:00:00', null, null, null, "
            "timestamp_ntz'2026-06-10 00:00:00', false, id, current_timestamp() "
            f"from range({10 * month}, {10 * month + 10})"
        )

    result = walkthrough(spark, rows=10, appends=3)

    assert result["after_rollback"] == result["rows"] + 15
    assert result["after_accident"] < result["after_rollback"]
    assert result["after_undo"] == result["after_accident"]
    assert result["files_before"] > result["files_after"] == 1
    assert result["snapshots_after_expire"] == 1
    assert spark.table(f"{DEMO}.snapshots").count() == 1
    # 10 rows from the CTAS and 3 x 5 from the inserts: no order_id taken twice, and the same
    # orders on every run, the first 25 of silver.
    keys = spark.sql(f"select count(*), count(distinct order_id) from {DEMO}").first()
    assert tuple(keys) == (25, 25)  # type: ignore[arg-type]
    ids = sorted(row.order_id for row in spark.table(DEMO).select("order_id").collect())
    assert ids == [f"o{i}" for i in range(30, 55)]
    # Every state change is printed, so replaying the transcript reaches the same state.
    transcript = capsys.readouterr().out
    assert f"delete from {DEMO}" in transcript
    assert transcript.count("system.rollback_to_snapshot") == 2
    # The current snapshot's files are printed on both sides of the compaction: N, then 1.
    sections = transcript.split("\n=== ")
    files = [i for i, s in enumerate(sections) if f"from {DEMO}.files" in s]
    compaction = next(i for i, s in enumerate(sections) if "system.rewrite_data_files" in s)
    referenced = next(i for i, s in enumerate(sections) if f"from {DEMO}.all_data_files" in s)
    assert [first_cell(sections[i]) for i in files] == [str(result["files_before"]), "1"]
    assert files[0] < compaction < files[1] < referenced
    # Each payoff is printed right after its step: all 25 rows after the first rollback, one
    # snapshot after the expire.
    rollback = next(i for i, s in enumerate(sections) if "system.rollback_to_snapshot" in s)
    assert f"select count(*) from {DEMO}\n" in sections[rollback + 1]
    assert first_cell(sections[rollback + 1]) == "25"
    expire = next(i for i, s in enumerate(sections) if "system.expire_snapshots" in s)
    assert f"from {DEMO}.snapshots\n" in sections[expire + 1]
    assert first_cell(sections[expire + 1]) == "1"
    assert "Cannot find snapshot with ID" in sections[-1]


@needs_iceberg
def test_demo_fails_when_an_expired_snapshot_is_still_readable(spark: SparkSession) -> None:
    table = f"{CATALOG}.demo.still_readable"
    spark.sql(f"create namespace if not exists {CATALOG}.demo")
    spark.sql(f"create table {table} using iceberg as select 1 as id")
    live = spark.table(f"{table}.snapshots").select("snapshot_id").collect()[0][0]

    with pytest.raises(RuntimeError, match=str(live)):
        iceberg_demo.show_time_travel_fails(spark, table, live)
