# Connector status FAILED

Symptom: `make connector-status` shows FAILED for the connector or its task; bronze stops growing
while the replayer writes.

1. Read the trace: `curl -s 127.0.0.1:8083/connectors/shop-connector/status | python3 -m json.tool`.
2. Postgres was restarted or unreachable: once `postgres-oltp` is healthy, restart the task with
   `curl -X POST '127.0.0.1:8083/connectors/shop-connector/restart?includeTasks=true'`. The slot
   kept its position; the connector resumes from its stored offset.
3. A topic is missing (the producer blocks, `UNKNOWN_TOPIC_OR_PARTITION` in `make logs
   S=kafka-connect`): `bash connect/register.sh` creates the topics, `oltp.message` included, and
   re-applies the config. It is idempotent. The task can stay RUNNING while the producer blocks:
   `ConnectorNotRunning` does not fire, only bronze stops growing.
4. `RecordTooLargeException` in the trace: someone wrote a `pg_logical_emit_message` over about
   6.3 MB (the 8 MB producer limit applies to the base64 the converter writes). The record stays in
   the WAL, and a restart fails on it again. Ask the owner: the way out (a larger limit for one
   drain, or skipping the record) changes the connector or loses data.
5. The container is gone after `docker kill`: `docker start lakehouse-kafka-connect-1`. A killed
   worker did not commit its last offsets, so bronze receives the events since the last offset
   flush (up to 60 s) a second time, with the same LSN. Silver absorbs them (ADR-021). To check,
   let the replayer stop and bronze catch up, run `make silver`, then run from the repo root, with
   the UTC time 90 s before the kill (the first copy of a repeated event can be in bronze up to
   60 s before it):
   `bash -c '. scripts/chaos/lib.sh && lsn_duplicates_since "YYYY-MM-DD HH:MM:SS" && reconcile'`.
   It runs in a child shell because `lib.sh` sets `set -euo pipefail` and exports `.env`:
   sourced into your own shell, a DIFF from `reconcile` would close it.
6. Never drop the replication slot or the `connect-offsets` topic to "fix" it: that forces a new
   initial snapshot and is on the blast-radius list.
