"""scripts/chaos/silver-kill.sh against a fake `docker`: no container, no stack, no replay.

The real script and the real lib.sh run in a temporary root. The fake answers by what the log of
its own calls says: the unpause of silver_upsert makes the scheduler create a run and start the
merge container, `docker kill` ends it, and the first look at the DAG run (after the kill) means
the retry has healed silver. $DOCKER_CALLS holds every call of docker and curl, so a test can say
what was never called (`docker rm`, a trigger, an airflow call in the hot loop before the kill)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TABLES = ("customers", "order_items", "orders", "payments", "products", "reviews", "sellers")

# The fake knows three moments: before the unpause, between unpause and kill, after the kill.
# $SCENARIO picks the oddity: pre_existing (a container before the start), synced (burst brought
# nothing), leftover (container remains after the run), all_merged (the kill lands after the last
# table), or nothing (the happy path). Env switches add the rest: REPLAYER_UP, NO_SCHEDULER,
# SILVER_PAUSED, FINAL_DIFF, OFFSETS_BAD, BURST_FAIL, BREAK (reconcile fails before or after the
# kill), NO_MERGE_LINES, RUNNING (which runs the REST API lists: own, two, queued_besides,
# queued_only, none), TRIES (the try_number of the merge task), TI_STATE, LOG_DUP, KILL_FAIL (the
# container ended before the kill), LOGS_GONE (the log vanishes after the first look), KILL_REMOVES
# (the container is gone after the kill), MORE_AFTER_KILL (a table logged between detection and
# kill), TI_FAIL, VARIABLE_FAIL, SNAPSHOT_FAIL, QUARANTINE_FAIL (a read that fails after the kill).
# Airflow 3 prints is_paused as the strings "True" and "False".
FAKE_DOCKER = r"""#!/usr/bin/env bash
echo "$*" >>"$DOCKER_CALLS"
called() { grep -q -- "$1" "$DOCKER_CALLS"; }
unpaused() { called 'dags unpause silver_upsert'; }
killed() { called '^kill '; }
healed() { called ' dags list-runs silver_upsert -o json'; }
dag_json='[{"dag_id": "silver_upsert", "is_paused": "'"${SILVER_PAUSED:-False}"'"},
  {"dag_id": "dbt_build", "is_paused": "'"${DBT_PAUSED:-False}"'"},
  {"dag_id": "dq_checks", "is_paused": "False"},
  {"dag_id": "iceberg_maintenance", "is_paused": "True"}]'
lake_synced() {  # does silver equal Postgres for table $1 at this moment
  [ "$SCENARIO" = synced ] && return 0
  [ -n "${FINAL_DIFF:-}" ] && [ "$1" = orders ] && return 1
  healed && return 0
  if killed; then
    [ "$SCENARIO" = all_merged ] && return 0
    [ "$1" = customers ] && return 0
  fi
  return 1
}
case "$*" in
  *"ps -q airflow-scheduler"*) [ -n "${NO_SCHEDULER:-}" ] || echo scheduler ;;
  "ps -a --filter"*)
    case "$SCENARIO" in
      pre_existing) echo abc123 ;;
      leftover) killed && echo abc123 ;;
    esac
    exit 0 ;;
  "logs lakehouse-silver-merge"*)
    unpaused || exit 1
    if killed && [ -n "${KILL_REMOVES:-}" ]; then exit 1; fi
    if [ -n "${LOGS_GONE:-}" ]; then
      [ ! -e "$STATE_DIR/looked" ] || exit 1
      touch "$STATE_DIR/looked"
      echo "starting the merge"
      exit 0
    fi
    [ -z "${NO_MERGE_LINES:-}" ] || exit 0
    [ -z "${MORE_AFTER_KILL:-}" ] || ! killed ||
      echo "batch 3: 4 events merged into lake.silver.orders in 1.0 s"
    [ -z "${LOG_DUP:-}" ] || echo "batch 2: 1 events merged into lake.silver.customers in 1.0 s"
    echo "batch 3: 5 events merged into lake.silver.customers in 1.0 s"
    echo "batch 3: 9 events merged into lake.silver.order_items in 2.0 s" ;;
  kill*) [ -z "${KILL_FAIL:-}" ] || exit 1 ;;
  rm*) exit 0 ;;
  *"airflow dags list -o json"*) echo "$dag_json" ;;
  *"dags pause "*|*"dags unpause "*) exit 0 ;;
  *"dags list-runs "*)
    id="scheduled__2026-11-05T10:00:00+00:00"
    echo "[{\"run_id\": \"$id\", \"state\": \"${DAG_STATE:-success}\"}]" ;;
  *"airflow variables get "*)
    [ -z "${VARIABLE_FAIL:-}" ] || exit 1
    echo "UserWarning: noise"; echo "${VARIABLE:-777}" ;;
  *" exec -T kafka "*) echo "oltp.shop.orders:0:5" ;;
  *" exec -T postgres-oltp "*) echo "5 k" ;;
  *" exec -T trino "*)
    case "$*" in
      *silver.quarantine*)
        if killed; then
          [ -z "${QUARANTINE_FAIL:-}" ] || exit 1
          echo "${QUARANTINE_AFTER:-3}"
        else echo 3; fi ;;
      *'$snapshots'*) [ -z "${SNAPSHOT_FAIL:-}" ] || ! killed || exit 1; echo 777 ;;
      *"max(kafka_offset) + 1 as varchar"*) echo "oltp.shop.orders:0:5" ;;
      *"having count(*) >"*) echo "${OFFSETS_BAD:-0}" ;;
      *)
        case "${BREAK:-}" in
          before) unpaused || exit 1 ;;
          after) killed && ! healed && exit 1 ;;
        esac
        t=$(echo "$*" | grep -o 'silver\.[a-z_]*' | head -1 | cut -d. -f2)
        if lake_synced "$t"; then echo "5 k"; else echo "4 k"; fi ;;
    esac ;;
  *) exit 0 ;;
esac
"""

# The burst: replay_burst runs `.venv/bin/python -m replayer start` under `timeout`, which ends
# it with 124 when it still runs. A marker file tells that the burst started.
FAKE_PYTHON = (
    '#!/usr/bin/env bash\ntouch "$STATE_DIR/burst-started"\n'
    '[ -z "${BURST_FAIL:-}" ] || exit 1\nexec sleep 20\n'
)
# curl: the replayer health probe (answers only when REPLAYER_UP is set) and the REST API of the
# api-server: a token, the active runs of silver_upsert (created by the scheduler once the DAG is
# unpaused) and the merge task instance of the run. Every call goes to the same log as docker's.
FAKE_CURL = r"""#!/usr/bin/env bash
echo "curl $*" >>"$DOCKER_CALLS"
run='"dag_run_id": "scheduled__2026-11-05T10:00:00+00:00"'
other='"dag_run_id": "x"'
running='"state": "running"'
queued='"state": "queued"'
case "$*" in
  *:8000/health*) [ -n "${REPLAYER_UP:-}" ] && exit 0; exit 7 ;;
  *auth/token*) echo '{"access_token": "t"}' ;;
  *"/dagRuns?"*)
    grep -q 'dags unpause silver_upsert' "$DOCKER_CALLS" || { echo '{"dag_runs": []}'; exit 0; }
    grep -q '^kill ' "$DOCKER_CALLS" && { echo '{"dag_runs": []}'; exit 0; }
    case "${RUNNING:-own}" in
      own) echo "{\"dag_runs\": [{$run, \"state\": \"running\"}]}" ;;
      two) echo "{\"dag_runs\": [{$run, $running}, {$other, $running}]}" ;;
      queued_besides) echo "{\"dag_runs\": [{$run, $running}, {$other, $queued}]}" ;;
      queued_only) echo "{\"dag_runs\": [{$run, $queued}]}" ;;
      none) echo '{"dag_runs": []}' ;;
    esac ;;
  *"/taskInstances/merge"*)
    [ -z "${TI_FAIL:-}" ] || exit 22
    echo "{\"task_id\": \"merge\", \"state\": \"${TI_STATE:-success}\"," \
      "\"try_number\": ${TRIES:-2}}" ;;
  *) exit 7 ;;
esac
"""


def run_script(
    tmp_path: Path, scenario: str = "nothing", **env: str
) -> tuple[subprocess.CompletedProcess[str], list[str], Path]:
    root = tmp_path / "root"
    (root / "scripts" / "chaos").mkdir(parents=True)
    for name in ("chaos/silver-kill.sh", "chaos/lib.sh", "reconcile_sql.py"):
        shutil.copy(REPO / "scripts" / name, root / "scripts" / name)
    shutil.copytree(REPO / "contracts" / "silver", root / "contracts" / "silver")
    shutil.copytree(
        REPO / "airflow" / "dags" / "lakehouse", root / "airflow" / "dags" / "lakehouse"
    )
    (root / ".env").write_text("OLTP_USER=user\nOLTP_DB=db\n")
    (root / ".venv" / "bin").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    for path, body in (
        (bin_dir / "docker", FAKE_DOCKER),
        (bin_dir / "curl", FAKE_CURL),
        (root / ".venv" / "bin" / "python", FAKE_PYTHON),
    ):
        path.write_text(body)
        path.chmod(0o755)
    calls = tmp_path / "docker-calls"
    calls.touch()
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    result = subprocess.run(
        ["bash", str(root / "scripts" / "chaos" / "silver-kill.sh")],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "DOCKER_CALLS": str(calls),
            "STATE_DIR": str(state),
            "TMPDIR": str(scratch),
            "SCENARIO": scenario,
            "SILVER_KILL_BURST": "1",
            "SILVER_KILL_SETTLE": "0",
            "SILVER_KILL_POLL": "1",
            "SILVER_KILL_START_WAIT": "10",
            "SILVER_KILL_WAIT": "10",
            **env,
        },
    )
    return result, calls.read_text().splitlines(), state


def test_existing_container_refuses_before_any_pause_or_burst(tmp_path: Path) -> None:
    result, calls, state = run_script(tmp_path, "pre_existing")

    assert result.returncode == 1, result.stderr
    assert "lakehouse-silver-merge exists" in result.stderr
    assert "409" in result.stderr
    assert not (state / "burst-started").exists()
    assert not any(" dags pause " in call or " dags unpause " in call for call in calls)


def test_burst_that_brought_nothing_refuses_and_gives_the_pauses_back(tmp_path: Path) -> None:
    result, calls, state = run_script(tmp_path, "synced")

    assert result.returncode == 1, result.stderr
    assert "burst brought nothing to merge" in result.stderr
    assert (state / "burst-started").exists()
    assert not any(" dags trigger " in call for call in calls)
    assert not any(call.startswith("kill ") for call in calls)
    assert not any("dagRuns" in call for call in calls)
    for dag in ("silver_upsert", "dbt_build", "dq_checks"):
        assert any(call.endswith(f"dags unpause {dag}") for call in calls)


def test_kill_and_retry_that_heals_ends_ok(tmp_path: Path) -> None:
    result, calls, _ = run_script(tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == "silver-kill ok"
    assert "run scheduled__2026-11-05T10:00:00+00:00 is running" in result.stdout
    assert "killed lakehouse-silver-merge" in result.stdout
    assert "2 of 7 tables with events were merged" in result.stdout
    assert "6 tables differ from Postgres right after the kill" in result.stdout
    assert "scenario" not in result.stdout
    assert calls.count("kill lakehouse-silver-merge") == 1
    # The pause comes before the burst, the unpause before the kill, and nothing triggers a run:
    # the merge killed is the one the scheduler made, and the retry is proved on that very run.
    pause = next(i for i, c in enumerate(calls) if c.endswith("dags pause silver_upsert"))
    unpause = next(i for i, c in enumerate(calls) if c.endswith("dags unpause silver_upsert"))
    kill = calls.index("kill lakehouse-silver-merge")
    assert pause < unpause < kill
    assert not any(" dags trigger " in call for call in calls)
    assert not any(call.startswith("rm ") for call in calls)
    assert any(
        "dagRuns/scheduled__2026-11-05T10:00:00+00:00/taskInstances/merge" in c for c in calls
    )


def test_nothing_but_docker_logs_runs_between_the_first_look_and_the_kill(
    tmp_path: Path,
) -> None:
    # Every airflow or REST call costs seconds, the window between the first and the last table
    # is 4 to 11 s: after the run is known, only `docker logs` may run until the kill.
    result, calls, _ = run_script(tmp_path)

    assert result.returncode == 0, result.stderr
    kill = calls.index("kill lakehouse-silver-merge")
    first_look = next(i for i, c in enumerate(calls) if c.startswith("logs "))
    assert first_look < kill
    assert all(c.startswith("logs ") for c in calls[first_look:kill]), calls[first_look:kill]
    run_known = max(i for i, c in enumerate(calls[:first_look]) if "dagRuns?" in c)
    assert not any("airflow" in c or c.startswith("curl") for c in calls[run_known + 1 : kill])


def test_kill_after_the_last_table_is_inconclusive(tmp_path: Path) -> None:
    result, _, _ = run_script(tmp_path, "all_merged")

    assert result.returncode == 1, result.stderr
    assert "inconclusive: the kill came after the last table" in result.stderr
    assert "silver-kill ok" not in result.stdout


def test_container_left_after_the_retry_refuses_with_409_and_never_removes_it(
    tmp_path: Path,
) -> None:
    result, calls, _ = run_script(tmp_path, "leftover")

    assert result.returncode == 1, result.stderr
    assert "409" in result.stderr
    assert "OPERATIONS.md, Timeouts" in result.stderr
    assert "silver-kill ok" not in result.stdout
    assert not any(call.startswith("rm ") or " rm " in call for call in calls)


def test_a_dag_run_that_failed_is_not_ok(tmp_path: Path) -> None:
    result, _, _ = run_script(tmp_path, DAG_STATE="failed")

    assert result.returncode == 1, result.stderr
    assert "ended failed" in result.stderr
    assert "silver-kill ok" not in result.stdout


def test_quarantine_that_grew_is_not_ok(tmp_path: Path) -> None:
    result, _, _ = run_script(tmp_path, QUARANTINE_AFTER="4")

    assert result.returncode == 1, result.stderr
    assert "silver.quarantine grew from 3 to 4 rows" in result.stderr


def test_variable_that_is_not_the_last_snapshot_is_not_ok(tmp_path: Path) -> None:
    result, _, _ = run_script(tmp_path, VARIABLE="700")

    assert result.returncode == 1, result.stderr
    assert "LAST_BRONZE_SNAPSHOT is 700, the last bronze snapshot is 777" in result.stderr


@pytest.mark.parametrize("scenario", ["nothing", "synced"])
def test_only_the_dags_the_script_paused_are_unpaused(tmp_path: Path, scenario: str) -> None:
    # dbt_build was paused before the run: the script neither pauses nor unpauses it.
    result, calls, _ = run_script(tmp_path, scenario, DBT_PAUSED="True")

    assert result.returncode == (0 if scenario == "nothing" else 1), result.stderr
    assert not any(call.endswith(" dbt_build") and "pause" in call for call in calls)
    for dag in ("silver_upsert", "dq_checks"):
        assert any(call.endswith(f"dags pause {dag}") for call in calls)
        assert any(call.endswith(f"dags unpause {dag}") for call in calls)


def test_the_tables_of_the_fake_are_the_contracts() -> None:
    # The fake answers per table; a new contract would silently count as "not synced".
    assert tuple(sorted(p.stem for p in (REPO / "contracts" / "silver").glob("*.json"))) == TABLES


def refused(result: subprocess.CompletedProcess[str], calls: list[str], text: str) -> None:
    assert result.returncode == 1, result.stderr
    assert text in result.stderr
    assert "silver-kill ok" not in result.stdout
    assert not any(c.startswith("kill ") for c in calls)


def test_a_live_replayer_refuses_before_any_pause(tmp_path: Path) -> None:
    result, calls, state = run_script(tmp_path, REPLAYER_UP="1")

    assert result.returncode == 2, result.stderr
    assert "a replayer already answers" in result.stderr
    assert not (state / "burst-started").exists()
    assert not any(" dags pause " in call for call in calls)


def test_no_scheduler_refuses_before_any_pause(tmp_path: Path) -> None:
    result, calls, _ = run_script(tmp_path, NO_SCHEDULER="1")

    refused(result, calls, "airflow-scheduler is not running")
    assert not any(" dags pause " in call for call in calls)


@pytest.mark.parametrize("value", ["True", "true"])
def test_silver_upsert_paused_before_the_run_refuses(tmp_path: Path, value: str) -> None:
    result, calls, _ = run_script(tmp_path, SILVER_PAUSED=value)

    refused(result, calls, "silver_upsert is paused already")
    assert not any(" dags pause " in call or " dags unpause " in call for call in calls)


def test_a_failed_burst_refuses_before_the_unpause_wait(tmp_path: Path) -> None:
    result, calls, _ = run_script(tmp_path, BURST_FAIL="1")

    refused(result, calls, "the replay burst failed")
    assert not any("dagRuns" in c for c in calls)
    assert any(call.endswith("dags unpause silver_upsert") for call in calls)


def test_reconcile_that_cannot_run_before_the_merge_refuses(tmp_path: Path) -> None:
    result, calls, _ = run_script(tmp_path, BREAK="before")

    refused(result, calls, "reconcile could not run before the merge")
    assert not any("dagRuns" in c for c in calls)


def test_reconcile_that_cannot_run_after_the_kill_refuses(tmp_path: Path) -> None:
    result, calls, _ = run_script(tmp_path, BREAK="after")

    assert result.returncode == 1, result.stderr
    assert "reconcile could not run after the kill" in result.stderr
    assert calls.count("kill lakehouse-silver-merge") == 1


def test_merge_that_never_shows_a_table_is_inconclusive_and_never_killed(
    tmp_path: Path,
) -> None:
    result, calls, _ = run_script(tmp_path, NO_MERGE_LINES="1", SILVER_KILL_START_WAIT="2")

    refused(result, calls, "no running lakehouse-silver-merge with a merged table within 2 s")


def test_final_reconcile_that_differs_is_not_ok(tmp_path: Path) -> None:
    result, _, _ = run_script(tmp_path, FINAL_DIFF="1")

    assert result.returncode == 1, result.stderr
    assert "reconcile is not 7/7 after the retry" in result.stderr
    assert "silver-kill ok" not in result.stdout


def test_bad_bronze_offsets_are_not_ok(tmp_path: Path) -> None:
    result, _, _ = run_script(tmp_path, OFFSETS_BAD="1")

    assert result.returncode == 1, result.stderr
    assert "a Kafka offset is in bronze twice or missing" in result.stderr


@pytest.mark.parametrize("running", ["two", "queued_besides", "queued_only"])
def test_another_or_a_queued_run_is_inconclusive_without_a_kill(
    tmp_path: Path, running: str
) -> None:
    result, calls, _ = run_script(tmp_path, RUNNING=running)

    refused(result, calls, "inconclusive: another run")
    assert any(call.endswith("dags unpause dq_checks") for call in calls)
    assert not any(c.startswith("logs ") for c in calls)


def test_no_run_after_the_unpause_is_inconclusive_without_a_kill(tmp_path: Path) -> None:
    result, calls, _ = run_script(tmp_path, RUNNING="none", SILVER_KILL_START_WAIT="2")

    refused(result, calls, "no run of silver_upsert started within 2 s")
    assert any(call.endswith("dags unpause dq_checks") for call in calls)


def test_a_merge_task_with_one_attempt_does_not_prove_the_retry(tmp_path: Path) -> None:
    result, _, _ = run_script(tmp_path, TRIES="1")

    assert result.returncode == 1, result.stderr
    assert "the merge task of the run had 1 attempt" in result.stderr
    assert "silver-kill ok" not in result.stdout


def test_a_table_logged_twice_counts_once(tmp_path: Path) -> None:
    result, _, _ = run_script(tmp_path, LOG_DUP="1")

    assert result.returncode == 0, result.stderr
    assert "2 of 7 tables with events were merged" in result.stdout


def test_a_container_that_ended_before_the_kill_is_inconclusive(tmp_path: Path) -> None:
    result, _, _ = run_script(tmp_path, KILL_FAIL="1")

    assert result.returncode == 1, result.stderr
    assert "inconclusive: the merge ended before the kill, run again" in result.stderr
    assert "docker kill" not in result.stderr


def test_a_log_that_vanishes_before_a_table_is_inconclusive_without_a_kill(
    tmp_path: Path,
) -> None:
    result, calls, _ = run_script(tmp_path, LOGS_GONE="1")

    refused(result, calls, "inconclusive: the merge ended before a table was seen")


def test_the_tables_merged_are_counted_from_the_log_after_the_kill(tmp_path: Path) -> None:
    result, _, _ = run_script(tmp_path, MORE_AFTER_KILL="1")

    assert result.returncode == 0, result.stderr
    assert "3 of 7 tables with events were merged" in result.stdout


def test_a_container_gone_after_the_kill_keeps_the_count_seen_before_it(tmp_path: Path) -> None:
    result, _, _ = run_script(tmp_path, KILL_REMOVES="1")

    assert result.returncode == 0, result.stderr
    assert "2 of 7 tables with events were merged" in result.stdout


@pytest.mark.parametrize(
    ("switch", "text"),
    [
        ("TI_FAIL", "could not read the merge task instance of scheduled__"),
        ("VARIABLE_FAIL", "could not read LAST_BRONZE_SNAPSHOT or the last bronze snapshot"),
        ("SNAPSHOT_FAIL", "could not read LAST_BRONZE_SNAPSHOT or the last bronze snapshot"),
        ("QUARANTINE_FAIL", "could not read silver.quarantine after the retry"),
    ],
)
def test_a_read_that_fails_at_the_end_is_not_ok(tmp_path: Path, switch: str, text: str) -> None:
    result, _, _ = run_script(tmp_path, **{switch: "1"})

    assert result.returncode == 1, result.stderr
    assert text in result.stderr
    assert "silver-kill ok" not in result.stdout


def test_a_merge_task_that_is_not_a_success_is_not_ok(tmp_path: Path) -> None:
    result, _, _ = run_script(tmp_path, TI_STATE="up_for_retry")

    assert result.returncode == 1, result.stderr
    assert "the merge task of the run is up_for_retry" in result.stderr
