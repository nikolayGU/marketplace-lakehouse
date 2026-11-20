# Container restarted or target down (ContainerRestarting, ScrapeTargetDown)

## ContainerRestarting

Symptom: alert `ContainerRestarting` (warn): `docker_container_start_time_seconds` of a compose
container changed in the last 15 minutes. `docker restart` moves the start time, while
`RestartCount` follows only the restart policy. The label `name` says which container. It does
not count the one-shot services (`minio-init`, `lakekeeper-migrate`, `lakekeeper-bootstrap`,
`superset-init`), nor `lakehouse-silver-merge` and `docker compose run` containers: their names do
not end in a number. `spark-bronze` in a loop also fires `SparkRestartLoop`
(`spark-stalled.md`).

1. Which one and why: `docker inspect -f '{{.RestartCount}} {{.State.OOMKilled}}' <name>`.
   `OOMKilled` true: the memory limit; `docker stats --no-stream` shows use against it. A limit
   change is a compose change for the owner. `RestartCount` above 0: the restart policy ran; read
   `make logs S=<service>`. Both 0: someone ran `docker restart` or `compose up` recreated it.
2. Planned restarts, nothing to fix (the alert is noisy by design, 15 minutes after each):
   the verify cycle stops the scheduler (`make verify` refuses while it runs,
   `scripts/verify.sh:43-50`) and starts it again; `superset` is restarted after an edit of
   `superset_config.py` (OPERATIONS.md, "Superset").
3. After a Docker restart `kafka-exporter` and `lakekeeper` start before their dependencies are
   healthy and start again, so the alert burns for 15 minutes. Wait, then `make status`
   until all are `healthy`; `make report` lists containers that stayed down.
4. The stateful job (`spark-orders-per-minute`, profile `stateful`) was seen failing after a
   host sleep, with `RestartCount` 1: the restart policy brought it back and its checkpoint was
   intact. Check the log for `Resuming at batch N` (`spark-stalled.md`, step 4).
5. A merge killed by a chaos script or a timeout starts again under the same name; it is not
   counted. The retry shows in Airflow as `try_number` 2 (OPERATIONS.md, scenario 10b).

Reproduce: `docker restart <name>` of any compose container; the alert fired 15 s after the
restart (OPERATIONS.md, scenarios 5 and 8).

## ScrapeTargetDown

Symptom: alert `ScrapeTargetDown` (warn): `up == 0` for 2 minutes for a Prometheus target. The job
`spark-orders-per-minute` is excluded: it is down by design without `PROFILE=stateful`. A target
that is down silences its own alerts, so fix this first.

1. Which target: `curl -s 127.0.0.1:9090/api/v1/targets | python3 -c 'import json,sys; t=json.load(sys.stdin)["data"]["activeTargets"]; print(sorted((x["labels"]["job"], x["health"]) for x in t if x["health"] != "up"))'`
2. The container behind the job: `make status`. Down or unhealthy: `make logs S=<service>`.
3. `container-exporter` down with a permission error in its log: `DOCKER_GID` in `.env`; an empty
   container list fails the scrape too, which means `COMPOSE_PROJECT_NAME` does not match the
   stack. Exporter healthchecks and what else can fail: `../../OPERATIONS.md#observability`.
4. Prometheus itself down: no rule is evaluated and nothing is delivered (no Alertmanager).
   `make report` lists project containers that are down although their policy is
   `unless-stopped`.

Reproduce: stop an exporter and wait 2 minutes. Not run live: covered by promtool
(`make alerts-test`).
