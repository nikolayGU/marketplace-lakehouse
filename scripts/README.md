# scripts

- `make_env.py`: generates `.env`.
- `fetch_data.py` (W1-T03): downloads Olist into `data/raw` via Kaggle CLI or explains manual download.
- `chaos/<name>.sh`: failure scenarios, one per file, each prints the verification SQL at the end.
- `make iceberg-demo` is not a script here: it runs `streaming/spark_jobs/iceberg_demo.py`.
- `lakekeeper/bootstrap.sh` (W2-T09): bootstraps Lakekeeper and creates the warehouse on MinIO;
  runs in the compose one-shot `lakekeeper-bootstrap` (`make lakekeeper-bootstrap`), safe to re-run.
- `lakekeeper/register.sh` (W2-T09): registers the bronze and silver tables of the JDBC catalog in
  Lakekeeper and checks that both catalogs point at the same metadata file; host-side, before the
  cutover, with Spark stopped (it refuses otherwise). How to run it, and why a registration is
  never undone with a drop: `OPERATIONS.md`, "Lakekeeper (REST catalog)".
