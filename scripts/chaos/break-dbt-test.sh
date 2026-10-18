#!/usr/bin/env bash
# Chaos 9: a dbt test fails inside Airflow. dbt_build goes red, every model after fct_orders is
# skipped and the marts keep their previous snapshot; a run without the switch is green again
# (OPERATIONS.md, scenario 9). Needs orchestrate up with dbt_build unpaused, and no replay: a
# silver merge in between would start another dbt_build and change the marts.
. "$(dirname "$0")/lib.sh"

paused=$(airflow_cli dags list -o json 2>/dev/null | python3 -c '
import json, sys
lines = sys.stdin.read().splitlines()
start = next(i for i, line in enumerate(lines) if line.strip() == "[" or line.lstrip().startswith("[{"))
print(next(str(d["is_paused"]) for d in json.loads("\n".join(lines[start:])) if d["dag_id"] == "dbt_build"))')
if [ "$paused" != False ]; then
  echo "dbt_build is paused (or not there): unpause it first, a paused DAG only queues runs" >&2
  exit 2
fi
no_other_replayer

snapshots() { trino_value "select count(*) from gold.\"mart_daily_sales\$snapshots\""; }
run=chaos9-$(date -u +%Y%m%dT%H%M%S)

before=$(snapshots)
run_dag dbt_build "$run-broken" '{"dbt_vars": "{chaos_break_test: true}"}' || true
state=$(dag_run_state dbt_build "$run-broken")
after=$(snapshots)
echo "dbt_build $run-broken: $state; mart_daily_sales snapshots before $before, after $after"
if [ "$state" != failed ]; then
  echo "FAIL: the run with the switch ended $state, expected failed" >&2
  exit 1
fi
if [ "$before" != "$after" ]; then
  echo "FAIL: mart_daily_sales changed although a test upstream of it failed" >&2
  exit 1
fi

run_dag dbt_build "$run-fixed" || {
  echo "FAIL: dbt_build without the switch did not recover" >&2
  exit 1
}
echo "ok: the failed run left the marts as they were; the run without the switch is green"
