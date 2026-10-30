# Disk full

Symptom: a container stops with `No space left on device`, Postgres refuses writes, Kafka or MinIO
log write errors. No alert watches the disk; the slot alerts (`SlotWalRetainedHigh`) are the only
early sign for the biggest grower.

Not proven live: no full disk was run on this stack. The steps below only read until step 4.

1. Which disk? The stack runs on Docker Desktop: volumes and images live on the disk of its VM,
   not on the WSL root filesystem, so `df -h /` in WSL does not show them. Free space as a
   container sees it: `docker run --rm -v lakehouse_minio:/v:ro alpine df -h /v` (any project
   volume shows the same VM disk). What takes it: `docker system df -v` (images, build cache,
   volumes). On 2026-10-30 `docker system df` showed images 24.8 GB (9.2 GB reclaimable) and 9 GB
   of build cache: the usual weight is images, not data.
2. The replication slot. In `make psql`:
   `select slot_name, active, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) from pg_replication_slots`.
   Postgres keeps every WAL file the slot has not confirmed (`max_slot_wal_keep_size = -1`). Large
   and growing: `slot-wal-growth.md`. Do not drop the slot to free space: the events in between
   are gone (ADR-019, owner's decision).
3. The other growers, read only: Kafka keeps 24 h and at most 2 GiB per partition
   (`KAFKA_LOG_RETENTION_BYTES` in compose), so up to 6 GiB for a three-partition `oltp.shop.*`
   topic; MinIO grows with snapshots until maintenance expires
   them (OPERATIONS.md, "Maintenance"); container logs are capped by the `json-file` rotation
   (20 MB, 3 files).
4. Freeing space is the owner's call, one command at a time; an agent proposes and does not run
   it. Least risky first: the Docker build cache (`docker builder prune`), then unused images.
   `docker system prune --volumes`, `docker volume rm`, `make nuke`, checkpoint or bucket deletes,
   retention changes and `expire_snapshots` are blast radius (AGENTS.md).
5. After space is back: `make status` until every service is `healthy`, then `make verify-fast`.
   A Spark job that died on a failed write resumes from its checkpoint; a Postgres that stopped
   replays its WAL on start.
