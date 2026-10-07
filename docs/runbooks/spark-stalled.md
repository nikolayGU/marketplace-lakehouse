# Spark job without a batch for 5 minutes

Symptom: `spark_streaming_last_batch_timestamp` (spark-bronze, `127.0.0.1:4041/metrics`) older
than 5 minutes, or absent because the target is down (`up` = 0, the driver is gone); the container
is unhealthy, exited or restarting.

1. State: `docker inspect -f '{{.State.Status}} {{.RestartCount}}' lakehouse-spark-bronze-1`.
   Exited after `docker kill` or `docker stop`: `docker start lakehouse-spark-bronze-1`. The
   restart policy does not cover manual stops.
2. Restart loop with `OffsetOutOfRange` or "data loss" in `make logs S=spark-bronze`: the job was
   down longer than Kafka retention (24 h). Do not delete the checkpoint. Recover the missing
   history with `make cdc-snapshot` (OPERATIONS.md, Bronze ingest); the decision to skip the lost
   offsets is the owner's.
3. Running but unhealthy: the query is stuck, typically in a commit to MinIO or the catalog in
   `postgres-meta`. Check `postgres-meta` and `minio` (`make status`), then
   `docker restart lakehouse-spark-bronze-1`. The checkpoint replays the unfinished batch, and
   Iceberg skips an epoch it already committed.
4. After any restart the log shows `Resuming at batch N`. Verify from the repo root with
   `bash -c '. scripts/chaos/lib.sh && bronze_offsets_report'`: no duplicates and no holes in any
   partition. The child shell matters: `lib.sh` sets `set -euo pipefail` and exports `.env`.
5. Files written by a batch that never committed stay in MinIO as orphans until
   `remove_orphan_files` (maintenance, week 5). They take space, not correctness.
