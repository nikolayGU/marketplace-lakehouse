"""Prometheus metrics from the driver (ADR-013). Kafka lag lands with W4-T02."""

import time

from prometheus_client import Counter, Gauge, start_http_server
from pyspark.sql.streaming.listener import (
    QueryIdleEvent,
    QueryProgressEvent,
    QueryStartedEvent,
    QueryTerminatedEvent,
    StreamingQueryListener,
)

LAST_BATCH = Gauge(
    "spark_streaming_last_batch_timestamp",
    "Unix time of the last progress or idle event",
    ["query"],
)
INPUT_ROWS = Counter("spark_streaming_input_rows_total", "Rows read by micro-batches", ["query"])
BATCH_DURATION = Gauge(
    "spark_streaming_batch_duration_seconds", "Wall time of the last micro-batch", ["query"]
)


class PrometheusListener(StreamingQueryListener):
    """Since Spark 3.5 a query with no new data reports `onQueryIdle` instead of progress, every
    `noDataProgressEventInterval` (10 s). Both move LAST_BATCH, so it only freezes when the
    query is stuck, not when the topic is quiet."""

    def __init__(self) -> None:
        super().__init__()
        self._names: dict[str, str] = {}

    def onQueryStarted(self, event: QueryStartedEvent) -> None:
        self._names[str(event.id)] = event.name or str(event.id)

    def onQueryProgress(self, event: QueryProgressEvent) -> None:
        progress = event.progress
        name = progress.name or str(progress.id)
        LAST_BATCH.labels(name).set(time.time())
        INPUT_ROWS.labels(name).inc(progress.numInputRows)
        BATCH_DURATION.labels(name).set(progress.batchDuration / 1000)

    def onQueryIdle(self, event: QueryIdleEvent) -> None:
        LAST_BATCH.labels(self._names.get(str(event.id), str(event.id))).set(time.time())

    def onQueryTerminated(self, event: QueryTerminatedEvent) -> None:
        pass


def start_metrics(port: int) -> PrometheusListener:
    start_http_server(port)
    return PrometheusListener()
