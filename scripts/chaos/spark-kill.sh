#!/usr/bin/env bash
# Chaos 1: kill spark-bronze while a micro-batch is running, start it again, and prove bronze
# holds every Kafka offset exactly once (OPERATIONS.md, scenario 1).
. "$(dirname "$0")/lib.sh"

container=lakehouse-spark-bronze-1
ui=http://127.0.0.1:4040/api/v1/applications
running_job() {
  local app
  app=$(curl -sf "$ui" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["id"])')
  curl -sf "$ui/$app/jobs?status=running" |
    python3 -c 'import json,sys; sys.exit(not json.load(sys.stdin))'
}

no_other_replayer
# The burst runs in a process group of its own, so an early exit or ctrl-c stops all of it.
set -m
replay_burst 150 &
burst=$!
set +m
stop_burst() { kill -TERM -- -"$burst" 2>/dev/null || true; }
trap stop_burst EXIT

wait_until 120 "a running micro-batch" running_job
kill -0 "$burst" 2>/dev/null ||
  { echo "the replay burst ended before the kill; its log is above" >&2; exit 1; }
# docker kill counts as a manual stop: restart: unless-stopped will not bring it back.
trap 'stop_burst; docker start "$container" >/dev/null' EXIT
docker kill "$container" >/dev/null
echo "killed $container at $(date -u +%T) after the Spark UI reported a running job"
sleep 5
docker start "$container" >/dev/null
trap stop_burst EXIT
started=$(docker inspect -f '{{.State.StartedAt}}' "$container")
wait_until 300 "$container to turn healthy" healthy "$container"
echo "started $container at ${started:11:8}, healthy at $(date -u +%T)"

# Spark logs "Resuming at batch N" on every start. Only a batch that was planned and never
# committed resumes with committed offsets (end of N-1) different from available ones (end of N).
resume=$(docker logs --since "$started" "$container" 2>&1 | grep -m1 'Resuming at batch') || true
batch=${resume#*Resuming at batch }
batch=${batch%% *}
committed=${resume#*with committed offsets }
committed=${committed%% and available offsets *}
if [ -z "$resume" ] || [ "$committed" = "${resume##* and available offsets }" ]; then
  echo "inconclusive: Spark replayed no uncommitted batch, the kill landed between batches;" \
    "run again" >&2
  exit 1
fi
echo "Spark replayed batch $batch, which the kill interrupted"

wait "$burst"
trap - EXIT
wait_until 300 "bronze to catch up with Kafka" bronze_caught_up

docker logs --since "$started" "$container" 2>&1 | grep 'Skipping epoch' | cut -c1-110 || true
bronze_offsets_report
trino "with s as (
         select committed_at, element_at(summary, 'spark.sql.streaming.queryId') as query_id,
                cast(element_at(summary, 'spark.sql.streaming.epochId') as bigint) as epoch,
                element_at(summary, 'added-records') as records
         from bronze.\"cdc_events\$snapshots\"
         where element_at(summary, 'spark.sql.streaming.queryId') is not null)
       select committed_at, epoch, records from s
       where query_id = (select max_by(query_id, committed_at) from s)
         and epoch between $batch - 1 and $batch + 1
       order by committed_at"

bad=$(trino_value "select count(*) from (
                     select topic, kafka_partition from bronze.cdc_events group by 1, 2
                     having count(*) > count(distinct kafka_offset)
                       or max(kafka_offset) - min(kafka_offset) + 1
                         > count(distinct kafka_offset))")
if [ "$bad" != 0 ]; then
  echo "FAIL: $bad topic partitions with duplicate or missing offsets" >&2
  exit 1
fi
# Grouped by query id: a new checkpoint starts a new query whose epochs count from 0 again.
repeated=$(trino_value "select count(*) from (
                          select 1 from bronze.\"cdc_events\$snapshots\"
                          where element_at(summary, 'spark.sql.streaming.epochId') is not null
                          group by element_at(summary, 'spark.sql.streaming.queryId'),
                                   element_at(summary, 'spark.sql.streaming.epochId')
                          having count(*) > 1)")
if [ "$repeated" != 0 ]; then
  echo "FAIL: $repeated epochs committed twice by one query" >&2
  exit 1
fi
echo "ok: every Kafka offset is in bronze exactly once; no epoch was committed twice"
