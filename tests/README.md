# tests

- `unit/`: envelope fixtures and silver contracts against `contracts/` and the source schema,
  dedup and LSN-guard logic (local SparkSession, `local[1]`), replayer virtual clock and date
  shifting.
- `fixtures/envelopes/`: Debezium records shaped after the live topics, ids replaced.
- Spark tests skip on a host without Java; `make test-spark` runs them in the Spark image
  (`SPARK_TESTS` in the Makefile lists the files; `SPARK_IMAGE` picks the image, CI uses
  `lakehouse/spark:ci`). Inside the image a skip fails the run, so the MERGE, quarantine and
  epoch tests cannot be silently skipped.
- Integration checks run through `make chaos-*` and `.github/workflows/smoke.yml`, not pytest.
- `test_workflows.py` guards the workflows (every Dockerfile in the hadolint matrix, action tags,
  no secrets but `GITHUB_TOKEN`, smoke triggers).
