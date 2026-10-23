"""Prometheus metrics from the driver (ADR-013): Kafka lag from the progress offsets, and for
stateful queries the state size, the watermark and the rows it dropped (W5-T01b)."""

import time

from prometheus_client import Counter, Gauge, start_http_server
from pyspark.sql.streaming.listener import (
    QueryIdleEvent,
    QueryProgressEvent,
    QueryStartedEvent,
    QueryTerminatedEvent,
    StreamingQueryListener,
)

from spark_jobs.offsets import kafka_lag
from spark_jobs.progress import state_totals, watermark_seconds

LAST_BATCH = Gauge(
    "spark_streaming_last_batch_timestamp",
    "Unix time of the last progress or idle event",
    ["query"],
)
INPUT_ROWS = Counter("spark_streaming_input_rows_total", "Rows read by micro-batches", ["query"])
BATCH_DURATION = Gauge(
    "spark_streaming_batch_duration_seconds", "Wall time of the last micro-batch", ["query"]
)
KAFKA_LAG = Gauge(
    "spark_streaming_kafka_lag",
    "Messages in Kafka past the last micro-batch (latestOffset minus endOffset), 0 when idle",
    ["query", "topic", "partition"],
)
STATE_ROWS = Gauge(
    "spark_streaming_state_rows", "Rows held in the state of stateful operators", ["query"]
)
WATERMARK = Gauge(
    "spark_streaming_watermark_timestamp_seconds",
    "Event-time watermark as Unix seconds; the time of the data, not of the clock",
    ["query"],
)
LATE_ROWS = Counter(
    "spark_streaming_late_rows_dropped_total",
    "Rows the watermark dropped as too late",
    ["query"],
)


class PrometheusListener(StreamingQueryListener):
    """Since Spark 3.5 a query with no new data reports `onQueryIdle` instead of progress, every
    `noDataProgressEventInterval` (10 s). Both move LAST_BATCH, so it only freezes when the
    query is stuck, not when the topic is quiet.

    Kafka lag is `latestOffset - endOffset` of the last progress. Idle means no new data, so every
    lag row of that query goes to 0; otherwise the last value would hang there forever."""

    def __init__(self) -> None:
        super().__init__()
        self._names: dict[str, str] = {}
        self._lag_rows: dict[str, set[tuple[str, int]]] = {}

    def onQueryStarted(self, event: QueryStartedEvent) -> None:
        self._names[str(event.id)] = event.name or str(event.id)

    def onQueryProgress(self, event: QueryProgressEvent) -> None:
        progress = event.progress
        name = progress.name or str(progress.id)
        LAST_BATCH.labels(name).set(time.time())
        INPUT_ROWS.labels(name).inc(progress.numInputRows)
        BATCH_DURATION.labels(name).set(progress.batchDuration / 1000)
        operators = getattr(progress, "stateOperators", None)
        if operators:
            held, dropped = state_totals(operators)
            STATE_ROWS.labels(name).set(held)
            LATE_ROWS.labels(name).inc(dropped)
            watermark = watermark_seconds(getattr(progress, "eventTime", None))
            if watermark is not None:
                WATERMARK.labels(name).set(watermark)
        for source in progress.sources:
            for (topic, partition), lag in kafka_lag(source.endOffset, source.latestOffset).items():
                KAFKA_LAG.labels(name, topic, str(partition)).set(lag)
                self._lag_rows.setdefault(name, set()).add((topic, partition))

    def onQueryIdle(self, event: QueryIdleEvent) -> None:
        name = self._names.get(str(event.id), str(event.id))
        LAST_BATCH.labels(name).set(time.time())
        for topic, partition in self._lag_rows.get(name, ()):
            KAFKA_LAG.labels(name, topic, str(partition)).set(0)

    def onQueryTerminated(self, event: QueryTerminatedEvent) -> None:
        pass


def start_metrics(port: int) -> PrometheusListener:
    start_http_server(port)
    return PrometheusListener()
