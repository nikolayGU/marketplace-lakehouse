# Failure scenarios

What each `make chaos-<name>` target breaks and what it proved. The index with dates is in [OPERATIONS](../OPERATIONS.md#failure-scenarios).

Each scenario is a `make chaos-<name>` target plus a written answer to five questions:
what happened, what monitoring shows, which data is at risk, how the system recovers,
why nothing is lost or duplicated (or where it can be). Filled in as scenarios are run.


### Template

```
### <n>. <Scenario>

What happened:
What monitoring shows: (metric, alert, time to detect)
Data at risk:
Recovery: (automatic / manual, steps, time to recover)
Why no loss or duplication: (or where it is possible)
Verification SQL:
```

Every scenario prints its own verification; the helpers it uses (`bronze_offsets_report`,
`bronze_caught_up`, ...) live in `scripts/chaos/lib.sh`. The file sets `set -euo pipefail` and
exports `.env`, so run a helper from the repo root in a child shell, not sourced into your own:
`bash -c '. scripts/chaos/lib.sh && bronze_offsets_report'`. A scenario that plays a replay
burst on the host stops before it touches anything, its script exiting 2, while another replayer
answers on `127.0.0.1:8000` (the `oltp-replayer` container or `make replay-start`): the burst
could not bind the port, and that replayer would keep playing at its own `REPLAY_SPEED`.

### 1. Spark bronze killed mid-batch

`make chaos-spark-kill` plays about 30 virtual hours (150 s at 720x, `CHAOS_REPLAY_SPEED`), waits
until the Spark UI reports a running job, `docker kill`s `spark-bronze` and starts it 5 s later.
It then reads `Resuming at batch N` from the new log: equal committed and available offsets mean
the kill landed between batches, and the script exits 1 as inconclusive; otherwise it prints
`Spark replayed batch N`. After the replayer burst ends and bronze catches up with Kafka it fails
on any duplicate or missing offset and on any epoch one query committed twice.

What happened: the driver JVM died with a micro-batch in flight. Spark had written `offsets/N` to
the checkpoint but not `commits/N`, and Iceberg had no snapshot for epoch N. On 2026-10-07 the
kill came 4 s after `offsets/80` was written, while the first stage of batch 80 (ShuffleMapStage
0) was still reading Kafka: the write stage (ResultStage 1) was never submitted, so no data file
reached MinIO.
What monitoring shows: the container exits and stays down until it is started again (`docker
kill` counts as a manual stop, the restart policy does not apply). The `:4041` endpoint goes away
with the driver, so since W4 Prometheus scrapes it, the scrape
fails (`up` = 0) and Prometheus marks `spark_streaming_last_batch_timestamp` stale: Grafana shows
no data, not an old timestamp.
`SparkNoBatch5m` written as `time() - spark_streaming_last_batch_timestamp > 300` alone
would never fire here, so it also needs `absent(spark_streaming_last_batch_timestamp)`, for 5
minutes. After `docker start` the log says `Resuming at batch N`.
Data at risk: the batch in flight, 158 records in batch 80 on 2026-10-07 (`added-records` of its
snapshot). None is lost: Kafka keeps the records within retention, and bronze only misses the
batch until it is replayed.
Recovery: automatic after the container starts: Spark replays batch N from `offsets/N`. On
2026-10-07 the kill landed at 18:09:44 during batch 80 and the container started at 18:09:49; the
query logged `Resuming at batch 80` at 18:10:03, the replayed batch 80 committed at 18:10:12, 28 s
after the kill, with the same query id, and batch 81 followed. The container reported healthy at
18:10:17, about 28 s after the start (the script polls every 3 s). The first run, on 2026-09-26,
landed the same way (batch 47, 1 s after `offsets/47`, before the write stage) and also committed
the replayed batch 28 s after the kill.
Why no loss or duplication: the offsets come from the checkpoint, so nothing is skipped; a
replayed batch that Iceberg already committed is skipped by epoch (`Skipping epoch N`), because
the sink stores `spark.sql.streaming.queryId` and `epochId` in every snapshot summary. Both live
kills landed before the write stage, so no skip was needed and no `Skipping epoch` line appeared;
the commit-window case is reproduced deterministically by `tests/unit/test_iceberg_sink.py`. On
2026-10-07 the script ended with `ok`: no duplicate or missing offset in any of the 21 topic
partitions and no epoch committed twice. A kill during the write stage leaves the files already
written in MinIO as orphans until `remove_orphan_files`; neither run left any, since the
write stage never started.
Verification SQL (0 in both columns for every topic partition):

```
select topic, kafka_partition, count(*) - count(distinct kafka_offset) as duplicates,
       max(kafka_offset) - min(kafka_offset) + 1 - count(distinct kafka_offset) as missing
from bronze.cdc_events group by 1, 2 order by 1, 2;
```

### 2a. Kafka Connect restart

`make chaos-connect-restart` plays about 36 virtual hours (180 s at 720x) and 90 s into it runs
`docker restart lakehouse-kafka-connect-1`. It waits until the connector reports RUNNING and
`shop_slot` streams to a new walsender, lets the burst end and bronze catch up, and exits 1 as
inconclusive unless CDC events were produced both in the minute before the restart and after it.
Then it prints the events repeated with the same LSN, runs silver and compares live row counts
with Postgres (`reconcile`, which fails on any difference).

What happened: the worker got SIGTERM. On the way down it waited for the producer's acks and stored
the offset of the last acked record in `connect-offsets` (`Committing offsets for 1305 acknowledged
messages` on 2026-10-07); Debezium flushed that offset's last commit LSN to the replication slot,
which is behind the stored change LSN (offset `lsn=0/4F7298D0`, `lastCommitLsn=0/4F7221F8`, and
Postgres logged `Streaming transactions committing after 0/4F7221F8`). After the restart Postgres
re-sent the transactions committing after the slot position, and Debezium dropped everything up to
the stored offset (`identified as already processed`, then `switching off the filtering` at
`0/4F72B4D0`).
What monitoring shows: `make connector-status` is briefly unavailable, then RUNNING; the
Connect log shows `Committing offsets for N acknowledged messages` just before `Stopping down
connector`. Bronze stops growing for the restart and catches up afterwards.
Data at risk: none. The replayer kept writing; Postgres kept the WAL for the slot.
Recovery: automatic, about 32 s on 2026-10-07 (SIGTERM at 18:14:19, `Kafka Connect stopped` at
18:14:20.4, `Processing messages` at 18:14:50.7); about 40 s on 2026-09-26.
Why no loss or duplication: the final offset commit covered every record Kafka had acked, and on
resume Debezium filters whatever Postgres re-sends up to that offset, so nothing reached Kafka
twice. That holds while the stop fits Docker's 10 s stop timeout and the final commit fits
`offset.flush.timeout.ms` (5 s); otherwise expect repeats as in 2b. On 2026-10-07, with 1429 CDC
events produced in the minute before the restart and 1593 after it, 0 events repeated with the
same LSN, and live row counts of all seven silver tables matched Postgres; the 2026-09-26 run also
gave 0.

### 2b. Kafka Connect killed

`MODE=kill make chaos-connect-restart` does the same with `docker kill` and, 5 s later, `docker
start`. It also exits 1 as inconclusive when the kill repeated no event, which means it came
right after an offset flush.

What happened: no shutdown hook ran. Connect stores source offsets every 60 s
(`offset.flush.interval.ms`), so on restart it resumes from the last stored offset: Postgres
re-sends from the slot's last confirmed position, Debezium skips up to the stored offset, and every
event emitted after the stored offset is sent a second time with the same LSN.
What monitoring shows: the container is gone until someone starts it (a manual kill is not
restarted by the policy). A kill shorter than the `for: 1m` of `ConnectorNotRunning` does not trip
it; `ContainerRestarting` fires for `kafka-connect` (the start time moves, checked 2026-10-23
for Postgres and Kafka in scenarios 5 and 8). In bronze, repeated `(source_table,
key, lsn)`: the second copy arrives after the restart, the first can be up to 60 s older than the
kill.
Data at risk: none lost. Repeats only.
Recovery: `docker start lakehouse-kafka-connect-1`; the connector resumes by itself (on 2026-10-07
`Processing messages` at 18:20:30.0, 26 s after the start at 18:20:03.6).
Why no loss or duplication: nothing is lost because both positions are behind what reached
Kafka. The repeats land in bronze, which is at-least-once by contract, and silver's MERGE keeps
one row per key and ignores an equal LSN (ADR-021). On 2026-10-07 the kill came about 9 s after
the last offset flush (`Committing offsets for 728 acknowledged messages` at 18:19:49.2 in the
Connect log, walsender connection reset at 18:19:57.9 in the postgres-oltp log): 253 events
arrived twice (orders 173 on 152 keys, order_items 40, payments 39, reviews 1), their first copies
produced between 18:19:48.8 (not covered by that flush) and 18:19:57.4, and live row counts of all
seven silver tables still matched Postgres. On 2026-09-26 a kill about 2 s after the flush
repeated 11 events: the count follows the time since the last flush, up to 60 s of changes.
Verification SQL (the first copy can be in bronze up to 60 s before the kill, so the window starts
90 s before it; `make chaos-connect-restart` uses the run start instead, and on 2026-10-07 both
gave the same 253 events):

```
select source_table, count(distinct key) as keys_repeated, count(*) as events_repeated,
       sum(copies - 1) as extra_events
from (select source_table, key, lsn, count(*) as copies from bronze.cdc_events
      where ingest_ts >= timestamp '<kill time, UTC>' - interval '90' second and lsn is not null
      group by 1, 2, 3 having count(*) > 1)
group by 1;
```

### 3. Duplicate events from the source

`make chaos-duplicates` stops before it touches anything while another replayer answers on `:8000`
(the script exits 2, make prints `Error 2`; a failed check prints `Error 1`), waits until bronze has
caught up with Kafka so that the window holds only this run, prints the window start, and plays
about one virtual day (120 s at 720x) with `REPLAY_DUPLICATE_RATIO=0.1`. Once bronze has caught up
again it prints, per table, the UPDATEs, the no-op UPDATEs (`before = after`) with their share of
status UPDATEs, and the changes that arrived twice with the same LSN. It fails when orders got no
no-op UPDATE (the burst proved nothing) or when any change arrived twice with the same LSN (a
delivery repeat mixed in). Then it runs silver and fails unless silver holds, for every order whose
last event is a repeat, that repeat's LSN and status, and unless live row counts match Postgres.

What happened: the replayer picks `REPLAY_DUPLICATE_RATIO` of the orders (md5 of
`duplicate:<order_id>`) and runs every status UPDATE of a picked order twice, with the same values,
in one transaction. Postgres writes a second tuple version, so Debezium emits a second event with a
new LSN and `before` = `after`: a real change that changes nothing. On 2026-10-07 (UTC) the burst
moved the virtual clock from 2026-07-08 10:06 to 2026-07-09 10:03 (`make replay-status`), and bronze
took 2267 CDC events in the window (opened 2026-10-07 20:31:07 UTC).
What monitoring shows: the replayer counts the repeats (`replayer_events_total{kind="duplicate"}` on
its `/metrics`, `:8000` while the burst runs); nothing downstream reacts, by design.
`lakehouse_dq_lsn_repeats_last_hour` (`dq_checks`, repeats by `(source_table, key, lsn)`)
measures delivery repeats (chaos 2b) only: a source repeat is a new WAL record with a new LSN, so it
never counts there and shows instead as `op = 'u'` with `before = after`. The same check by hand is
`lsn_duplicates_since` in `scripts/chaos/lib.sh`.
Data at risk: none in silver. Bronze grows by the repeats (95 of the 2267 events in that run), and a
consumer that counts bronze events as business changes (status changes per day, say) counts each
repeat as one more: filter `before = after` out or read silver.
Recovery: nothing to recover; the next silver run absorbs the repeats. In that run the whole script
(burst, both catch-ups, silver, checks) took 3 min 11 s.
Why no loss or duplication: the repeat commits in the same transaction as its original, so a silver
batch usually holds both: `latest_per_key` keeps the repeat (higher LSN, same values) and MERGE
writes the row once. Only if a batch boundary splits the pair does MERGE rewrite the row with
identical values and a newer `_last_lsn` (one more row version in merge-on-read `silver.orders`, no
data change). Either way silver ends equal to Postgres. In that run orders had 1344 events and 1067
UPDATEs: 972 status changes and 95 no-op repeats, 9.8% of status UPDATEs, on 90 of the 926 orders
updated (85 with one repeat, 5 with two, one per status change); order_items (309 events), payments
(288) and reviews (326) had no UPDATE. 0 changes arrived twice with the same LSN, silver held the
repeat's LSN and status for all 90 orders whose last event is a repeat, and live row counts of all
seven silver tables matched Postgres (orders 93 860). The share is close to 10% because 90 picked of
926 is close to the expected 92.6: the ratio picks orders, not UPDATEs. The first run (burst on
2026-09-26, silver and `reconcile` ok on 2026-10-05 after the laptop slept) predates the asserts and
printed 18 no-op of 325 orders events, 5.5% of all orders events, a denominator the script no longer
uses; on status UPDATEs that is 18 of 120, 15.0%, on 16 of 114 orders: the fewer orders a burst
updates, the further the share can drift from the ratio.
Verification SQL (window start from the script's `window:` line; add an upper bound when later runs
followed, `ingest_ts < timestamp '2026-10-07 20:33:25'` for the numbers above, since bronze caught
up at 20:33:24):

```
select source_table, count(*) as events, count_if(op = 'u') as updates,
       count_if(op = 'u' and before = after) as no_op_updates,
       cast(100.0 * count_if(op = 'u' and before = after)
            / nullif(count_if(op = 'u' and before <> after), 0) as decimal(5, 1))
         as pct_of_status_updates,
       count(distinct key) filter (where op = 'u') as keys_updated,
       count(distinct key) filter (where op = 'u' and before = after) as keys_repeated
from bronze.cdc_events
where ingest_ts >= timestamp '<window start, UTC>'
group by 1 order by 1;
```

### 4. Late events

`make chaos-late` stops before it touches anything while another replayer answers on `:8000` (the
script exits 2), and before the burst when `shop-connector` or its task is not RUNNING or
`spark-bronze` is not healthy, naming the runbook (the script exits 1); `make` itself exits 2 on any
failure and shows the script's status as `Error 2` or `Error 1`. It prints the window start, plays
about one virtual day (120 s at 720x), waits until bronze has caught up and runs silver. It then
picks an order whose oldest change in the window (insert or update) has a newer one by LSN, and
fails unless silver already holds a higher `_last_lsn` for that order: at an equal one the row would
read the same afterwards and prove nothing, and with no row, a null or a lower one, MERGE would take
the re-sent change and the script would fail for the wrong reason. It reads that change back from
Kafka by partition and offset, produces it again with the same key, waits until bronze holds one
more copy of that LSN and runs silver again. It fails unless that run merged orders events (a run
that never read the record would also leave the row as it was) and unless silver's `order_status`
and `_last_lsn` for the order match before and after.

What happened: an older change of an order reached bronze after silver had applied a newer one.
Debezium does this after a kill (2b): everything sent since the last offset flush comes again with
the same LSN, behind newer changes that silver may already hold; a graceful restart (2a) re-sends
nothing. The script produces the record by hand, so the run does not depend on where a kill lands.
On 2026-10-07 (UTC) the burst moved the virtual clock from 2026-07-09 10:03 to 2026-07-10 10:00
(`make replay-status`), and bronze took 1180 events in the window (opened 2026-10-07 20:56:27 UTC),
the re-sent record included. Of the 350 orders the burst changed, 180 had more than one change, so
the pick is rarely short of candidates. It picked order `008819c6d5f6da6fa5cd9d50ca927cf4`: its
insert (`op = 'c'`, `created`, LSN 1401450968) and its update to `approved` (LSN 1401679552) came in
one bronze batch, and the first silver run left the row at `approved` with `_last_lsn` 1401679552.
The script re-sent the insert at 20:59:17 UTC. What monitoring shows: nothing reacts, by design.
Bronze takes one more record, and the second silver run logs an orders merge (`batch N: <k> events
merged into lake.silver.orders`) while the row stays. The repeat check by `(source_table, key, lsn)`
(`lsn_duplicates_since`, and the series `lakehouse_dq_lsn_repeats_last_hour` in `dq_checks`) counts
the re-sent record as one delivery repeat, as in 2b. In that run bronze took the record in at
20:59:20 UTC, and the second silver run logged `batch 15: 1 events merged into lake.silver.orders in
2.4 s`. The count was then the orders events the silver batch read from bronze (before quarantine
and before keeping one row per key), not rows MERGE changed. Since 2026-11-20 it counts the events
left after quarantine, still before keeping one row per key; a batch with none logs `batch N:
nothing to merge into lake.silver.<t>` and commits no snapshot. The snapshot that run committed had
`changed-partition-count` 0, no `added-records` and the same `total-records` (98812) as the first
run's. `lsn_duplicates_since` over the window reported orders with 1 key repeated and 1 extra event.
Data at risk: none in silver. Bronze keeps the re-sent record for good, at a new offset with the old
LSN: a consumer that reads bronze in offset or ingest order rather than by LSN sees the order go
back to its older status. Recovery: nothing to recover; the MERGE guard drops the event. In that run
the whole script (burst, catch-up, both silver runs, checks) took 3 min 12.6 s. Why no loss or
duplication: silver keeps one row per key, and MERGE updates a matched row only when `t._last_lsn is
null or s._last_lsn > t._last_lsn` (ADR-021; a null marks a row from an incremental snapshot read).
The re-sent change has a lower LSN than the row, so the row and its `_last_lsn` stay; an equal LSN
(a plain repeat, 2b) is skipped the same way. In that run bronze held LSN 1401450968 twice in
partition 1, both `created` with the same key and `after`: offset 74825, ingested at 20:57:40 UTC,
and the re-sent copy at offset 74855, at 20:59:20 UTC. Silver read `approved` with `_last_lsn`
1401679552 before and after, and the row's `_updated_at`, 20:59:03 UTC, is from the first silver
run, before the re-send.

Two meanings of "late". This scenario is late arrival: a change reaches the lake out of LSN order,
which here only a delivery repeat produces, and silver guards against it. `REPLAY_LATE_RATIO` with
`REPLAY_LATE_DELAY_SECONDS` is the other meaning: for that share of orders (md5 of
`late:<order_id>`) the replayer pushes the `delivered` update back by the delay in virtual time. The
change is late in event time for the windowed job (ADR-024, watermark), but it commits later, reaches
Kafka in order with a higher LSN, and gives silver nothing to guard against.
Verification SQL (order and stale LSN from the script's `re-sending` line):

```
select kafka_partition, kafka_offset, lsn,
       json_extract_scalar(after, '$.order_status') as status, ingest_ts
from bronze.cdc_events where lsn = <stale lsn> and source_table = 'orders';

select order_status, _last_lsn, _updated_at from silver.orders where order_id = '<order id>';

-- right after the script: the second silver run's snapshot changes no partition, adds no record
select committed_at, summary['changed-partition-count'] as changed_partitions,
       element_at(summary, 'added-records') as added_records,
       summary['total-records'] as total_records
from silver."orders$snapshots" order by committed_at desc limit 2;
```

### 5. PostgreSQL restart

```
make chaos-postgres-restart   # core + obs up, no replay running
```

What happened (2026-10-23): `docker compose restart postgres-oltp` with the connector streaming
and bronze caught up; the slot `shop_slot` stood at `0/5A7E0660`, walsender pid 16292. Postgres was
`healthy` 13 s later and the connector streamed from a new walsender 13 s later too, by itself:
the Debezium task retried and was never `FAILED`. The script then played a 30 s replay burst
(after the restart: the host replayer writes to Postgres and would die with it); bronze caught up 28 s
after the burst.
What monitoring shows: `ContainerRestarting` for `postgres-oltp` firing 15 s after the restart
(16:53:20 restart, 16:53:35 firing). The connector panel stays green; the restart is too short for
`ConnectorNotRunning` (`for: 1m`), and nothing else notices. If the task does not come back, the
script stops with the name of `docs/runbooks/connector-failed.md` and does not restart the task
itself, so the run shows the system's own answer.
Data at risk: none. The slot and its WAL survive a restart of Postgres, and the connector resumes
from `confirmed_flush_lsn`; events it had sent but not yet confirmed can be sent again with the same
LSN, and silver absorbs them (scenario 2b).
Recovery: automatic, 13 s.
Why no loss or duplication: the slot is durable in Postgres, offsets are in `connect-offsets`, bronze
keeps one row per Kafka offset (`bronze_offsets_ok`), silver merges by key and LSN.
Verification: the script ends with `bronze_offsets_ok`, `merge_silver` (the `silver_upsert` DAG while
the scheduler runs) and `reconcile`: 7 of 7 tables ok.

### 6. Connector stopped for 30 minutes (WAL growth)

```
make chaos-connect-pause   # HOLD=1800 s by default; core + obs up, no replay running
```

What happened (2026-10-23), two runs of two versions of the script. The 30-minute run (18:21:55)
was an uncommitted version that padded the WAL with `pg_logical_emit_message`; that stopped CDC
(below), so its "bronze caught up 19 s after the resume, `reconcile` 7 of 7" measured bronze
against a Kafka that had stopped growing, and its recovery was by hand: the topic, the producer
setting, a recreated Connect. `PUT /connectors/shop-connector/stop` (not `pause`: a paused task keeps
its walsender and the slot stays active) turned the slot inactive 4 s later; a 30 s burst
and padding took it from 11 MB to 80.9 MB. The committed script (`f606670`) ran once, with a hold
of 60 s (19:14), and did the same with 83.9 MB held; after the resume and a 15 s burst the connector had
confirmed everything (28 kB unconfirmed) and `restart_lsn` retained 3.9 MB.
What monitoring shows: `ConnectorNotRunning` 95 s after the stop (75 s in the rerun) and
`SlotWalRetainedHigh` 326 s after it (`for: 5m` plus the scrape; both runs). `dq_checks` also went
red with "differs at rest": bronze is quiet because nothing arrives, while the source writes. It now
says `in flight` for the whole stall and raises `CdcStalledSourceWrites` after about 20 minutes.
Run 2026-10-29 (full 1800 s hold, `make chaos-connect-pause`, exit 0): connector stopped
17:47:02 to 18:17:06 UTC; `dq_checks` at 18:00 and 18:15 green with "in flight: CDC
stands, no verdict"; `CdcStalledSourceWrites` firing at 18:20:04; after the resume nothing lost and
silver matching Postgres (rows, keys, sums) in all 7 tables.
Data at risk: none while the slot lives; Postgres keeps every WAL file it has not confirmed
(`max_slot_wal_keep_size = -1`), so the disk of the VM is the limit, and nothing but this alert
watches it (runbook `docs/runbooks/slot-wal-growth.md`). Replay alone writes ~1.1 MB of WAL per
virtual hour; the 64 MiB threshold is reached in about 2.5 virtual days of events.
Recovery: automatic once the connector runs (`resume`), minutes; proven with the committed script
for the full 1800 s hold on 2026-10-29 (above); an interrupted run is still to do. A script killed
mid-hold (INT, TERM, HUP, not KILL) resumes the connector from a trap: the STOPPED state survives a
Connect restart, so run it in the background, never under a tool timeout that sends SIGKILL.
Why no loss or duplication: the slot, `connect-offsets` and the Kafka offsets in bronze; checked
by `bronze_offsets_ok` and `reconcile`.
How the WAL is added, and what not to do: replay is too slow, so the script adds a transaction
and `pg_switch_wal()` per round (one 16 MB segment each; Debezium forwards nothing of it). The first
run used `pg_logical_emit_message` with 4 MB records instead, and that stopped CDC: Debezium decodes
logical messages and publishes them to `oltp.message`, a topic that does not exist (topic
auto-creation is off), and then hit the 1 MB `max.request.size` of the Connect producer. CDC stood
from about 18:52 to 19:00 with no loss; fixed by creating `oltp.message` (max message 8 MB,
retention 1 hour) and `CONNECT_PRODUCER_MAX_REQUEST_SIZE=8388608` in `docker/compose.yaml`, and the
connector drained 66 MB in seconds. The recovery also tried `pg_replication_slot_advance`, which would
have skipped the records; a permission check refused it. The setting stays,
and `connect/register.sh` now creates the topic (with `segment.ms` of an hour; the topic made by
hand got the same on 2026-10-29 with `kafka-configs.sh --alter --add-config segment.ms=3600000`,
when it was empty). The limit is on the encoded record:
JsonConverter writes the bytes as base64, so a message over about 6.3 MB still fails the task
(`RecordTooLargeException`, see `docs/runbooks/connector-failed.md`). Do not use logical messages.

### 7. Corrupted event in topic

```
make chaos-poison-event   # core up; with the Airflow scheduler running the merge is the silver_upsert DAG
```

What happened: one record that is not a Debezium envelope (`not json at all {poison-<ts>`) is
produced into `oltp.shop.orders`. Bronze keeps it as raw text (`raw` set, `op` null). The next
`silver_upsert` run routes it to `silver.quarantine` (`reason = unparsed_envelope`, topic, partition,
offset and payload kept) and carries on with the rest of the batch; a second run does not
quarantine it again.
What monitoring shows: the number of quarantined rows in the last hour is a line of the
`dq_checks` log (`dq quarantined_last_hour=<n>`, task `report`). It is deliberately not exported
to Prometheus and has no alert: `quarantine_rows_total` and its alert are the owner's Modify gate. The `lakehouse_dq_*` series cover duplicates, repeats and
reconciliation, not quarantine. Detection today is manual: `select reason, count(*) from
silver.quarantine group by 1`.
Data at risk: none. The record stays in bronze and in quarantine with its payload.
Recovery: nothing to recover; a human reads the payload and decides.
Why no loss or duplication: bronze is append-only and keeps the raw value; the quarantine key is
(topic, partition, offset), so a rerun merges onto the same row.
Verification: the script ends with one quarantine row for its marker after the first merge and
still one after the second.

### 8. Kafka down for 6 minutes

```
make chaos-kafka-down   # KAFKA_DOWN=360 by default; core + obs up, no replay running
```

What happened (2026-10-23): a 120 s replay burst started; 33 s into it `kafka` was stopped at
17:09:09 and kept down for 360 s, then started. Kafka was `healthy` 20 s after the start, the
connector `RUNNING` 20 s after (Connect had kept running and retried), bronze caught up 25 s
after. Spark did not wait: with the container stopped, the name `kafka` no longer resolves on the
compose network, the Kafka source fails with `No resolvable bootstrap urls given in
bootstrap.servers`, the query ends with an error and Docker restarts the driver about every 20 s
from 17:10:24 until Kafka was back at 17:15:10: 15 restarts (`RestartCount` 15). Each restart
resumed from the checkpoint.
What monitoring shows: `ContainerRestarting` for `kafka` and for `spark-bronze`, and
`ConnectorNotRunning`. `SparkNoBatch5m` did **not** fire: the series
`spark_streaming_last_batch_timestamp{query="bronze_cdc_ingest"}` was absent in one piece from
17:10:23 to 17:15:38 UTC, and Kafka was back before the 5 minutes of `for` of the `gone` rule were
over (`ALERTS` in the TSDB: `gone` pending from about 17:10:49 to 17:15:34, never firing), so a crash-looping driver is not seen through the last-batch age. The signal for it is
`SparkRestartLoop` (the rule was not loaded then, see [Alerts](../OPERATIONS.md#alerts)) and, as it was that day,
`ContainerRestarting`. A `dq_checks` run at 17:15 failed
with `silver differs from Postgres at rest`: bronze had been quiet for more than the 5 minutes that
count as "at rest", because the source could not deliver, while Postgres kept writing; that red run
raised `AirflowDagFailed`. It is a true signal (the pipeline is not delivering), through a check
that was written for another cause. Now a run stays red here when the slot moved in the
same 15 minutes before Kafka stopped (offset commit, heartbeat); otherwise it says `in flight`. The
stall (6 minutes) is shorter than the 20 minutes `CdcStalledSourceWrites` needs, so this scenario
does not fire it; chaos 6 does (shown live on 2026-10-29, scenario 6).
Data at risk: none while the outage is shorter than Kafka retention (24 h) and the slot lives.
Connect holds what it cannot produce, Postgres keeps the WAL. Longer than 24 h: scenario "Bronze
ingest" (`failOnDataLoss=true`).
Recovery: automatic, 25 s after Kafka returned.
Why no loss or duplication: offsets are per topic partition in Kafka and in the checkpoint; the 21
partitions hold no duplicate and no missing offset after the outage (`bronze_offsets_report`),
silver matches Postgres (rows, keys, sums) (7 of 7 ok).

### 9. Airflow task failure (dbt test)

```
make chaos-break-dbt-test   # orchestrate up, dbt_build unpaused, no replay running
```

What happened: `dbt_build` ran with the conf `{"dbt_vars": "{chaos_break_test: true}"}`. The
singular test `assert_chaos_break_test` on `fct_orders` returned every order under that switch and
failed.
What monitoring shows: `dbt_build` red in the Airflow UI; the task log names the test
(`Failure in test assert_chaos_break_test`). Alert `AirflowDagFailed` fired 17 s after the red run
ended (2026-10-23: run ended 16:39:47, the counter appeared at the 16:39:50 scrape, the alert at
16:40:05; 15 s evaluation plus the scrape). Seen in the UI when the run ends, 16 s after the trigger.
Data at risk: none. `fct_orders` was rebuilt before its test ran; every model after it was skipped,
so the marts kept their previous snapshot (`mart_daily_sales`: 9 snapshots before
and after).
Recovery: manual. Remove the cause (here the switch) and trigger `dbt_build`; the next silver merge
triggers it too. The run without the switch was green.
Why no loss or duplication: `dbt build` skips the children of a failed test, and a mart is either
replaced atomically (`CREATE OR REPLACE`) or not touched.
Verification SQL:

```
select committed_at, operation from gold."mart_daily_sales$snapshots"
order by committed_at desc limit 3;
```

### 10b. Silver merge killed between two tables

```
make chaos-silver-kill   # waits up to 6 min for the run the scheduler creates
```

What happened (2026-11-06): the script paused `silver_upsert`, `dbt_build` and `dq_checks`, played a
30 s burst and unpaused `silver_upsert` at 12:07:07 without triggering it. The scheduler created
`scheduled__2026-11-06T12:10:00+00:00`, started at 12:10:00 (REST). The script killed
`lakehouse-silver-merge` at 12:10:23, right after the first of the 4 tables with events
(`order_items`, 97 events in 2.9 s). The task failed with `DockerContainerFailedException`
(`StatusCode` 137) and, with `retries: 1` and `retry_delay` of one minute
(`airflow/dags/silver_upsert.py:36-37`), started attempt 2 at 12:11:24. The run ended `success` at
12:11:50 (REST; task `merge`, `try 2`, attempt 2 from 12:11:24 to 12:11:49 UTC).
What monitoring shows: `ContainerRestarting` for `lakehouse-silver-merge`, `activeAt` 12:11:34 UTC:
attempt 2 started a container with the same name, and the start time moved inside the 15 minute
window of the rule. Since the rule was changed to compose names that end in a number, the merge no
longer gives `ContainerRestarting`; the retry shows in Airflow as `try_number` 2.
`AirflowDagFailed` did not fire, because the run ended `success`. The failed
attempt is visible only in the task log and in the try number of the task.
Data at risk: none. Right after the kill silver was partly merged: 3 tables differed from Postgres
(`orders` 96258 against 96346, `payments` 100623 against 100715, `reviews` keys), `order_items` was
level (109178).
Recovery: automatic, by the Airflow retry. From the kill (12:10:23) to silver level with Postgres
(12:11:49): about 86 s, of which one minute is the retry delay.
Why no loss or duplication: bronze is append-only, so attempt 2 could read the same events again. It merged
`order_items` again (97 events, silver stays at 109178 rows with the same values, the MERGE is
keyed by primary key), then `orders` (155 events), `payments` (92) and `reviews` (2).
Verification: the script ends with `silver-kill ok` only if all of these hold after the retry: the
run state is `success`; `reconcile` is 7 of 7 (rows, keys, sums, values ok); every Kafka offset is in
bronze exactly once; `silver.quarantine` did not grow (4 rows before the burst); the Variable equals
the last bronze snapshot; task `merge` of that run is `success` with more than one try
(`scripts/chaos/silver-kill.sh:195-231`). A failed check after the retry ends with `FAIL: ...` and
exit 1. The script reports an inconclusive result only before or around the kill: another run is
already running or queued, the merge ended before its first table, the kill came too late to
catch it, or the kill came after the last table with events. Exit 0 on
2026-11-06; `make verify-fast` at 12:13 UTC: `verify ok`, 7 of 7. `dbt_build` stayed paused during
the run and its Asset event was lost ([Airflow](../OPERATIONS.md#airflow)), so gold lagged silver until `dbt_build` was
run by hand; now the `cleanup` of the script triggers `dbt_build` once after it
lifts its pause (`scripts/chaos/silver-kill.sh:41-52`).
