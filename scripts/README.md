# scripts

- `make_env.py`: generates `.env`.
- `bootstrap.sh` (`make bootstrap`): fresh clone to verified data; start, migrate,
  connector, load unless a replay state exists, verify, protect. Safe to re-run, deletes nothing.
- `verify.sh` (`make verify`): waits for bronze to catch up with Kafka, runs one silver
  merge, checks Kafka offsets in bronze, silver against Postgres and all seven tables in bronze;
  prints `verify ok`. Refuses (exit 2) while `airflow-scheduler` runs or a replayer plays, and when
  Trino does not answer `select 1`, catalog `lake` (Lakekeeper) does not answer `show schemas`, or
  MinIO does not answer a health check run in the trino container (not a table query: Trino
  caches metadata), within `TRINO_PROBE_WAIT` seconds (default 20) + 2 s each. `--no-merge`
  (`make verify-fast`) skips the merge. On success it stamps the git tree as it was when verify started (a file edited during the run is not covered) in `.verify-stamp` (`agent_state.py`); `verify-fast` keeps a `full` stamp that already covers the tree; a stamp that fails to write does not fail verify.
- `report.sh` (`make report`): git state, the verify, check and review stamps, containers and the
  replay clock for a session report. Reads only.
- `agent_state.py`: the three gate stamps, each a mode plus the git tree id of the working tree,
  which the commit-gate hooks in `.claude/hooks/` check before a commit (how the project was built: [evidence](../docs/evidence.md#how-it-was-built)). `.verify-stamp`: `make verify`
  and `make verify-fast`. `.check-stamp`: `make check`. `.review-stamp`: the hook `review_stamp.py`,
  from the verdict line of the `reviewer` report. `python3 scripts/agent_state.py tree <root>`
  prints the tree id, `show [verify|check|review] <root>` describes a stamp.
- `make check`: `make lint` and `make test`, then `agent_state.py stamp check`, so the commit gate
  sees that both passed on this working tree.
- `replay-burst.sh` (`make replay-burst SECONDS=<n> [SPEED=720]`): plays `n` real
  seconds of the replay schedule on the host, prints the virtual clock before and after.
- `reconcile_sql.py`: the Postgres and Trino queries `reconcile` (`chaos/lib.sh`) runs per silver
  contract: live row count, md5 of the sorted primary keys, sum of every decimal column, and the
  row fingerprint of every column that `dq_checks` uses (`airflow/dags/lakehouse/reconcile.py`).
- `fetch_data.py`: downloads Olist into `data/raw` via Kaggle CLI or explains manual download.
- `chaos/<name>.sh`: failure scenarios, one per file, each prints the verification SQL at the end.
- `make iceberg-demo` is not a script here: it runs `streaming/spark_jobs/iceberg_demo.py`.
- `lakekeeper/bootstrap.sh`: bootstraps Lakekeeper and creates the warehouse on MinIO;
  runs in the compose one-shot `lakekeeper-bootstrap`, which Spark and Trino wait for
  (`make lakekeeper-bootstrap` runs it alone), safe to re-run.
- `lakekeeper/protect.sh`: sets `protected` on every bronze and silver table in
  Lakekeeper, so a drop of one is refused with 409; host-side, safe to
  re-run. It never removes protection.
- `check-minio-images.sh <minio image> <mc image>`: checks the built MinIO and `mc` images
  (ADR-026) in a throwaway container; CI runs it in the job `minio-images`.
- `make_sample.py`: cuts the referentially closed 2 000-order Olist slice into `data/sample`, with a
  fixed seed.
- `obs/check_dashboards.py`: runs every panel query of the Grafana dashboards against Prometheus
  and Trino and exits 1 on a panel with no data that is not just idle.
- `demo/watermark.sh` (`make watermark-demo`): the watermark demo of `orders_per_minute` on a lab
  topic, one `availableNow` run per batch, into `lake.demo.orders_per_minute`.
