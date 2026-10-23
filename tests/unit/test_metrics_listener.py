from types import SimpleNamespace
from typing import Any, cast

from prometheus_client import REGISTRY
from spark_jobs.metrics import PrometheusListener

QUERY = "listener_test_query"


def _progress(
    end: str | None,
    latest: str | None,
    state: list[Any] | None = None,
    event_time: dict[str, str] | None = None,
    name: str = QUERY,
) -> Any:
    source = SimpleNamespace(endOffset=end, latestOffset=latest)
    return SimpleNamespace(
        progress=SimpleNamespace(
            name=name,
            id="q1",
            numInputRows=0,
            batchDuration=1000,
            sources=[source],
            stateOperators=state or [],
            eventTime=event_time or {},
        )
    )


def _lag(partition: str) -> float | None:
    labels = {"query": QUERY, "topic": "t", "partition": partition}
    return REGISTRY.get_sample_value("spark_streaming_kafka_lag", labels)


def test_progress_sets_lag_and_idle_zeroes_it() -> None:
    listener = PrometheusListener()
    listener.onQueryStarted(cast(Any, SimpleNamespace(id="q1", name=QUERY)))

    listener.onQueryProgress(_progress('{"t": {"0": 5}}', '{"t": {"0": 25, "1": 7}}'))
    assert _lag("0") == 20
    assert _lag("1") == 7

    listener.onQueryIdle(cast(Any, SimpleNamespace(id="q1")))
    assert _lag("0") == 0
    assert _lag("1") == 0


def test_first_batch_without_latest_offset_sets_nothing() -> None:
    # A query name of its own: the shared registry keeps the series other tests set.
    listener = PrometheusListener()
    listener.onQueryProgress(_progress(None, "null", name="listener_test_first_batch"))
    sample = REGISTRY.get_sample_value(
        "spark_streaming_kafka_lag",
        {"query": "listener_test_first_batch", "topic": "t", "partition": "0"},
    )
    assert sample is None


STATEFUL = "listener_test_stateful"


def _sample(metric: str) -> float | None:
    return REGISTRY.get_sample_value(metric, {"query": STATEFUL})


def test_state_rows_and_watermark_follow_the_progress() -> None:
    listener = PrometheusListener()
    operator = SimpleNamespace(numRowsTotal=3, numRowsDroppedByWatermark=0)

    listener.onQueryProgress(
        _progress(None, None, [operator], {"watermark": "2026-07-01T10:05:20.000Z"}, name=STATEFUL)
    )

    assert _sample("spark_streaming_state_rows") == 3
    assert _sample("spark_streaming_watermark_timestamp_seconds") == 1782900320


def test_late_rows_are_added_by_batch_not_by_total() -> None:
    listener = PrometheusListener()
    before = _sample("spark_streaming_late_rows_dropped_total") or 0

    for dropped in (2, 0, 1):
        operator = SimpleNamespace(numRowsTotal=1, numRowsDroppedByWatermark=dropped)
        listener.onQueryProgress(_progress(None, None, [operator], name=STATEFUL))

    assert (_sample("spark_streaming_late_rows_dropped_total") or 0) - before == 3


def test_a_query_without_state_gets_no_state_series() -> None:
    listener = PrometheusListener()
    listener.onQueryProgress(_progress(None, None, name="listener_test_stateless"))

    labels = {"query": "listener_test_stateless"}
    assert REGISTRY.get_sample_value("spark_streaming_state_rows", labels) is None
    assert REGISTRY.get_sample_value("spark_streaming_watermark_timestamp_seconds", labels) is None


def test_a_report_without_a_watermark_leaves_the_gauge_alone() -> None:
    listener = PrometheusListener()
    listener.onQueryProgress(
        _progress(
            None,
            None,
            [SimpleNamespace(numRowsTotal=1)],
            {"watermark": "2026-07-01T10:05:20Z"},
            name=STATEFUL,
        )
    )
    listener.onQueryProgress(
        _progress(None, None, [SimpleNamespace(numRowsTotal=1)], {}, name=STATEFUL)
    )

    assert _sample("spark_streaming_watermark_timestamp_seconds") == 1782900320
