# tests

- `unit/`: envelope parsing against `contracts/`, dedup and LSN-guard logic (local SparkSession,
  `local[1]`), replayer virtual clock and date shifting, compose invariants (every service has
  healthcheck, memory limit, profile, ports on `${BIND_IP}`).
- Integration checks run through `make chaos-*` and the smoke workflow, not pytest.
