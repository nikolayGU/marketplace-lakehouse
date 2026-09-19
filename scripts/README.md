# scripts

- `make_env.py`: generates `.env`.
- `fetch_data.py` (W1-T03): downloads Olist into `data/raw` via Kaggle CLI or explains manual download.
- `chaos/<name>.sh`: failure scenarios, one per file, each prints the verification SQL at the end.
- `iceberg/demo.sh`: snapshots, time travel, rollback, files before/after compaction.
- `lakekeeper-bootstrap.sh` (W1-T02): bootstrap and warehouse creation against MinIO.
