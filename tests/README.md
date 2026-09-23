# tests

- `unit/`: envelope fixtures and silver contracts against `contracts/` and the source schema,
  dedup and LSN-guard logic (local SparkSession, `local[1]`), replayer virtual clock and date
  shifting.
- `fixtures/envelopes/`: Debezium records shaped after the live topics, ids replaced.
- Spark tests skip on a host without Java; `make test-spark` runs them in the Spark image
  (`SPARK_TESTS` in the Makefile lists the files).
- Integration checks run through `make chaos-*` and the smoke workflow, not pytest.
