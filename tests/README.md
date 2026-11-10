# tests

- `unit/`: envelope fixtures and silver contracts against `contracts/` and the source schema,
  dedup and LSN-guard logic (local SparkSession, `local[1]`), replayer virtual clock and date
  shifting.
- `fixtures/envelopes/`: Debezium records shaped after the live topics, ids replaced.
- Spark tests skip on a host without Java; `make test-spark` runs them in the Spark image
  (`SPARK_TESTS` in the Makefile lists the files; `SPARK_IMAGE` picks the image, CI uses
  `lakehouse/spark:ci`). Inside the image a skip fails the run, so the MERGE, quarantine and
  epoch tests cannot be silently skipped.
- Postgres tests (`test_reconcile_postgres.py`) run in CI against a Postgres service
  (`.github/workflows/ci.yml`); `test_chaos_silver_kill.py` runs scenario 10b
  (`scripts/chaos/silver-kill.sh`) against a fake `docker`, no stack.
- Commit-gate hook tests: `unit/test_agent_hooks.py`.
- The live chaos scenarios (`make chaos-*`) and the clean-clone path (`.github/workflows/smoke.yml`)
  need a stack and stay outside pytest.
- `test_workflows.py` guards the workflows (every Dockerfile in the hadolint matrix, actions
  pinned by commit SHA, no secrets but `GITHUB_TOKEN`, smoke triggers).
