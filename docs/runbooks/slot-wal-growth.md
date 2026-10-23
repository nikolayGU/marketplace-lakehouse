# Retained WAL growing (SlotWalRetainedHigh)

Symptom: alert `SlotWalRetainedHigh` firing. `lakehouse_slot_retained_bytes{slot_name="shop_slot"}`
is above 64 MiB with `lakehouse_slot_active` 0 (nobody reads the slot), or above 512 MiB with the
slot active (a reader that cannot keep up). On this laptop an idle, healthy slot holds about
25 MB. Postgres keeps every WAL file the slot has not confirmed (`max_slot_wal_keep_size = -1`),
so the disk of the VM is what runs out, silently.

1. Is the connector there? `make connector-status`. `FAILED` or `STOPPED`: `connector-failed.md`.
   A connector stopped by hand (`PUT .../stop`) keeps that state across Connect restarts:
   `curl -X PUT http://127.0.0.1:8083/connectors/shop-connector/resume`.
2. Is Kafka there? `make status`. Connect holds events it cannot produce, and the slot does not
   advance. Start Kafka, wait for `healthy`, then for the connector.
3. Slot state: in `make psql`,
   `select slot_name, active, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) from pg_replication_slots`.
   Active and still growing: the reader is behind, look at `debezium_postgres_streaming_MilliSecondsBehindSource`
   and the Connect log.
4. After the reader is back it confirms what it read only once a real change arrives, and
   `restart_lsn` (what the alert reads) follows at the next running-transactions record: with no
   traffic the retained bytes do not fall. Wait for the next replay burst or source change, then
   watch the retained bytes fall under 64 MiB. Nothing is lost while the slot exists: Postgres keeps what it has not
   confirmed.
5. Do not drop the slot to free the disk. A new slot starts from the current LSN and the events
   in between are gone; that is a decision for the owner (`make cdc-snapshot` re-reads the tables,
   ADR-019).

Reproduce: `make chaos-connect-pause` (OPERATIONS.md, scenario 6).
