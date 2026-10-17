# scripts

- `make_env.py`: generates `.env`.
- `bootstrap.sh` (W3-T00, `make bootstrap`): fresh clone to verified data; start, migrate,
  connector, load unless a replay state exists, verify, protect. Safe to re-run, deletes nothing.
- `verify.sh` (W3-T00, `make verify`): waits for bronze to catch up with Kafka, runs one silver
  merge, checks Kafka offsets in bronze, silver against Postgres and all seven tables in bronze;
  prints `verify ok`. Refuses while `airflow-scheduler` runs or a replayer plays. `--no-merge`
  (`make verify-fast`) skips the merge. On success writes `.verify-stamp` (`agent_state.py`).
- `report.sh` (`make report`): git state, verify stamp, containers and the replay clock for a
  session report. Reads only.
- `agent_state.py`: the verify stamp, mode plus the git tree id of the working tree, which the
  agent hooks in `.claude/hooks/` check.
- `replay-burst.sh` (W3-T00, `make replay-burst SECONDS=<n> [SPEED=720]`): plays `n` real
  seconds of the replay schedule on the host, prints the virtual clock before and after.
- `reconcile_sql.py`: the Postgres and Trino queries `reconcile` (`chaos/lib.sh`) runs per silver
  contract: live row count, md5 of the sorted primary keys, sum of every decimal column.
- `fetch_data.py` (W1-T03): downloads Olist into `data/raw` via Kaggle CLI or explains manual download.
- `chaos/<name>.sh`: failure scenarios, one per file, each prints the verification SQL at the end.
- `make iceberg-demo` is not a script here: it runs `streaming/spark_jobs/iceberg_demo.py`.
- `lakekeeper/bootstrap.sh` (W2-T09): bootstraps Lakekeeper and creates the warehouse on MinIO;
  runs in the compose one-shot `lakekeeper-bootstrap`, which Spark and Trino wait for
  (`make lakekeeper-bootstrap` runs it alone), safe to re-run.
- `lakekeeper/register.sh` (W2-T09): registers the bronze and silver tables of the JDBC catalog in
  Lakekeeper and checks that both catalogs point at the same metadata file; host-side, before the
  cutover, with Spark stopped (it refuses otherwise). How to run it, and why a registration is
  never undone with a drop: `OPERATIONS.md`, "Lakekeeper (REST catalog)". The cutover runs it as
  its first step: `docs/runbooks/catalog-cutover.md`.
- `lakekeeper/protect.sh` (W2-T09): sets `protected` on every bronze and silver table in
  Lakekeeper, so a drop of one is refused with 409; host-side, after the cutover checks, safe to
  re-run. It never removes protection.
