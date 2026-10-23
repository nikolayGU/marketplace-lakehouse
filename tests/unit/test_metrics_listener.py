from types import SimpleNamespace
from typing import Any, cast

from prometheus_client import REGISTRY
from spark_jobs.metrics import PrometheusListener

QUERY = "listener_test_query"


def _progress(end: str | None, latest: str | None) -> Any:
    source = SimpleNamespace(endOffset=end, latestOffset=latest)
    return SimpleNamespace(
        progress=SimpleNamespace(
            name=QUERY, id="q1", numInputRows=0, batchDuration=1000, sources=[source]
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
    listener = PrometheusListener()
    listener.onQueryProgress(_progress(None, "null"))
    assert _lag("0") is None or _lag("0") == 0
