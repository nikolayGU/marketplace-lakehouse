"""The first steps of scripts/verify.sh after the replayer check: Trino answers `select 1`, then
catalog `lake` answers `show schemas`, then the object store answers a health check from the
Trino container. It runs the real script and the real lib.sh in a temporary
root, with `docker` and `curl` replaced by fakes first in PATH, so no container is touched. Without
the probes an unreachable Trino, or a live Trino whose catalog is down (Lakekeeper), made
`bronze_caught_up` fail on every try, and verify waited VERIFY_WAIT (900 s) and blamed Kafka."""

import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# What every run must stay under: the old code waited VERIFY_WAIT, here 600 s.
HARD_LIMIT = 10

# Every call is logged. $TRINO decides how `compose ... exec ... trino` answers, $LAKE how the same
# call answers when it names `--catalog lake`; a Kafka call fails, so a run that gets past the
# probes ends at "bronze did not catch up" without a stack.
# `hang` and `stubborn` start a child that outlives its parent unless the whole group is killed,
# and log its pid; `stubborn` also ignores SIGTERM, so only the kill after the grace period ends it.
# `slow` answers after 2 s.
FAKE_DOCKER = r"""#!/usr/bin/env bash
echo "$*" >>"$DOCKER_CALLS"
case "$*" in
  *" exec -T trino "*)
    state=$TRINO
    case "$*" in *"--catalog lake"*) state=$LAKE ;; esac
    # The storage probe is a curl health check run inside the Trino container; its state is $STORE.
    case "$*" in *"minio/health"*) state=$STORE ;; esac
    # Like the real CLI: a schema query without a session catalog is an error.
    case "$*" in
      *"--catalog lake"*) ;;
      *"show schemas"*) echo "Catalog must be specified when session catalog is not set" >&2
        exit 1 ;;
    esac
    # A healthy store runs the real command line, so the fake curl sees what the shell would pass.
    case "$*" in *"minio/health"*)
      if [ "$state" = up ]; then
        while [ "$1" != sh ]; do shift; done
        S3_ENDPOINT=http://in-container-minio:9000 "$@"
        exit $?
      fi ;;
    esac
    case "$state" in
      storedown) echo "curl: (6) Could not resolve host: minio" >&2; exit 6 ;;
      lakedown) echo "Query failed: lakekeeper refused the connection" >&2; exit 1 ;;
      down) echo 'service "trino" is not running' >&2; exit 1 ;;
      slow) sleep 2; echo 1; exit 0 ;;
      hang) sleep 30 & echo $! >>"$PIDS"; wait; exit 0 ;;
      stubborn) trap '' TERM; sleep 30 & echo $! >>"$PIDS"; wait; exit 0 ;;
      *) echo 1; exit 0 ;;
    esac ;;
  *" exec -T kafka "*) echo "kafka is not running" >&2; exit 1 ;;
  *) exit 0 ;;
esac
"""

# No replayer answers on :8000, whatever runs on the host that executes the tests.
# It logs its arguments to $CURL_CALLS and answers only to the health check of MinIO.
FAKE_CURL = r"""#!/usr/bin/env bash
echo "$*" >>"$CURL_CALLS"
case "$*" in *"minio/health"*) exit 0 ;; esac
exit 7
"""

PROBE = "exec -T trino trino --execute select 1"
LAKE_PROBE = "exec -T trino trino --catalog lake --execute show schemas"
# $S3_ENDPOINT stays literal here: it must be expanded by the shell inside the container.
STORE_PROBE = 'exec -T trino sh -c curl -sfS -o /dev/null -m "$1" "$S3_ENDPOINT/minio/health/live"'


def alive(pid: int) -> bool:
    # A zombie that init has not reaped yet is dead.
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1][0]
    except OSError:
        return False
    return state != "Z"


def run_verify(
    tmp_path: Path,
    mode: str,
    trino: str = "up",
    interrupt: signal.Signals | None = None,
    lake: str = "up",
    store: str = "up",
    wait_for: str = PROBE,
    **env: str,
) -> tuple[subprocess.CompletedProcess[str], list[str], float, list[int]]:
    # interrupt: sent to the bash process alone once the probe has started, as a terminal sends it
    # to the foreground group, where timeout is not: it runs the probe in a group of its own.
    # wait_for: the logged call the signal waits for, the first probe by default.
    root = tmp_path / "root"
    (root / "scripts" / "chaos").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "verify.sh", root / "scripts" / "verify.sh")
    shutil.copy(REPO / "scripts" / "chaos" / "lib.sh", root / "scripts" / "chaos" / "lib.sh")
    (root / ".env").write_text(
        "OLTP_USER=user\nOLTP_DB=db\nS3_ENDPOINT=http://host-side-minio:9000\n"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("docker", FAKE_DOCKER), ("curl", FAKE_CURL)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    calls = tmp_path / "docker-calls"
    calls.touch()
    pids = tmp_path / "pids"
    pids.touch()
    curl_calls = tmp_path / "curl-calls"
    curl_calls.touch()
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    argv = ["bash", str(root / "scripts" / "verify.sh")] + ([mode] if mode else [])
    started = time.monotonic()
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "DOCKER_CALLS": str(calls),
            "CURL_CALLS": str(curl_calls),
            "PIDS": str(pids),
            "TMPDIR": str(scratch),
            "TRINO": trino,
            "LAKE": lake,
            "STORE": store,
            "VERIFY_WAIT": "600",
            **env,
        },
    )
    if interrupt is not None:
        while not any(line.endswith(wait_for) for line in calls.read_text().splitlines()):
            if time.monotonic() - started > HARD_LIMIT:
                proc.kill()
                proc.wait()
                pytest.fail("verify.sh never started the probe")
            time.sleep(0.05)
        time.sleep(0.2)
        proc.send_signal(interrupt)
    try:
        stdout, stderr = proc.communicate(timeout=HARD_LIMIT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        pytest.fail(f"verify.sh still ran after {HARD_LIMIT} s: it waits instead of refusing")
    result = subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)
    seconds = time.monotonic() - started
    # Whatever the probe left behind goes first, so a failing run does not leave a sleep around.
    left = [pid for pid in map(int, pids.read_text().split()) if alive(pid)]
    for pid in left:
        os.kill(pid, signal.SIGKILL)
    assert not list(scratch.glob("trino_probe.*")), "the probe left its output file behind"
    return result, calls.read_text().splitlines(), seconds, left


@pytest.mark.parametrize("mode", ["--no-merge", ""])
def test_trino_not_running_refuses_with_exit_2_and_names_trino(tmp_path: Path, mode: str) -> None:
    result, calls, _, _ = run_verify(tmp_path, mode, trino="down")

    assert result.returncode == 2, result.stderr
    assert "verify failed: Trino probe failed:" in result.stderr
    assert 'service "trino" is not running' in result.stderr
    assert "does not answer" not in result.stderr
    assert "bronze did not catch up" not in result.stderr
    assert not any(" exec -T kafka " in call for call in calls)
    assert not any(call.endswith(LAKE_PROBE) for call in calls)


@pytest.mark.parametrize("mode", ["--no-merge", ""])
def test_catalog_lake_down_with_trino_alive_refuses_with_exit_2_and_names_the_catalog(
    tmp_path: Path, mode: str
) -> None:
    result, calls, seconds, _ = run_verify(tmp_path, mode, trino="up", lake="lakedown")

    assert result.returncode == 2, result.stderr
    assert "verify failed: Trino answers, but catalog lake fails" in result.stderr
    assert "lakekeeper refused the connection" in result.stderr
    assert "Trino probe failed" not in result.stderr
    assert "bronze did not catch up" not in result.stderr
    assert any(call.endswith(PROBE) for call in calls)
    assert any(call.endswith(LAKE_PROBE) for call in calls)
    assert not any(" exec -T kafka " in call for call in calls)
    assert seconds < HARD_LIMIT / 2


@pytest.mark.parametrize("mode", ["--no-merge", ""])
def test_catalog_lake_that_hangs_refuses_after_the_probe_limit(tmp_path: Path, mode: str) -> None:
    result, calls, seconds, left = run_verify(
        tmp_path, mode, trino="up", lake="hang", TRINO_PROBE_WAIT="1"
    )

    assert result.returncode == 2, result.stderr
    assert "verify failed: Trino answers, but catalog lake does not answer within 1 s" in (
        result.stderr
    )
    assert "bronze did not catch up" not in result.stderr
    assert seconds < 1 + 2
    assert not any(" exec -T kafka " in call for call in calls)
    assert not left, f"the probe left processes behind: {left}"


def test_catalog_lake_that_ignores_sigterm_is_killed_after_the_grace_period(tmp_path: Path) -> None:
    # Same as for Trino itself: timeout answers 137, still "does not answer".
    result, calls, seconds, _ = run_verify(
        tmp_path, "--no-merge", trino="up", lake="stubborn", TRINO_PROBE_WAIT="1"
    )

    assert result.returncode == 2, result.stderr
    assert "verify failed: Trino answers, but catalog lake does not answer within 1 s" in (
        result.stderr
    )
    assert any(call.endswith(LAKE_PROBE) for call in calls)
    assert seconds < 6


@pytest.mark.parametrize("mode", ["--no-merge", ""])
def test_ctrl_c_during_the_first_probe_does_not_start_the_catalog_probe(
    tmp_path: Path, mode: str
) -> None:
    # The first probe answers after 2 s, the second would hang: a signal that only the script gets
    # must stop it between the two, not after both.
    result, calls, seconds, _ = run_verify(
        tmp_path,
        mode,
        trino="slow",
        lake="hang",
        interrupt=signal.SIGINT,
        TRINO_PROBE_WAIT="3",
        VERIFY_WAIT="0",
    )

    assert result.returncode == 130, result.stderr
    assert "verify interrupted" in result.stderr
    assert not any(call.endswith(LAKE_PROBE) for call in calls)
    assert seconds < 2 + 2


@pytest.mark.parametrize("mode", ["--no-merge", ""])
@pytest.mark.parametrize("limit", ["1", "1.5"])
def test_trino_that_hangs_refuses_after_the_probe_limit(
    tmp_path: Path, mode: str, limit: str
) -> None:
    result, calls, seconds, left = run_verify(tmp_path, mode, trino="hang", TRINO_PROBE_WAIT=limit)

    assert result.returncode == 2, result.stderr
    assert f"verify failed: Trino does not answer within {limit} s" in result.stderr
    assert "bronze did not catch up" not in result.stderr
    assert seconds < float(limit) + 2
    assert not any(" exec -T kafka " in call for call in calls)
    assert not left, f"the probe left processes behind: {left}"


def test_trino_that_ignores_sigterm_is_killed_after_the_grace_period(tmp_path: Path) -> None:
    # timeout answers 137 here, not 124: still "does not answer", and the grace period ends it.
    # Whether the child of the probe dies too depends on the timeout of the host (GNU kills the
    # group again, uutils 0.8 only the probe), so it is not asserted.
    result, _, seconds, _ = run_verify(
        tmp_path, "--no-merge", trino="stubborn", TRINO_PROBE_WAIT="1"
    )

    assert result.returncode == 2, result.stderr
    assert "verify failed: Trino does not answer within 1 s" in result.stderr
    assert seconds < 6


@pytest.mark.parametrize("limit", ["0", "0.5", "-3", "abc", "1s"])
def test_invalid_probe_limit_refuses_without_probing(tmp_path: Path, limit: str) -> None:
    # timeout 0 means no limit at all, so a 0 must not reach it.
    result, calls, _, _ = run_verify(tmp_path, "--no-merge", trino="hang", TRINO_PROBE_WAIT=limit)

    assert result.returncode == 2, result.stderr
    assert (
        "verify failed: TRINO_PROBE_WAIT must be a number of seconds, at least 1" in result.stderr
    )
    assert f"'{limit}'" in result.stderr
    assert not any(call.endswith(PROBE) for call in calls)


@pytest.mark.parametrize("mode", ["--no-merge", ""])
def test_ctrl_c_during_a_hung_probe_exits_130_without_touching_bronze_or_silver(
    tmp_path: Path, mode: str
) -> None:
    result, calls, seconds, _ = run_verify(
        tmp_path, mode, trino="hang", interrupt=signal.SIGINT, TRINO_PROBE_WAIT="3", VERIFY_WAIT="0"
    )

    assert result.returncode == 130, result.stderr
    assert "verify interrupted" in result.stderr
    assert "verify failed" not in result.stderr
    assert seconds < 3 + 2 + 3
    assert not any(" exec -T kafka " in call or "spark-silver" in call for call in calls)


@pytest.mark.parametrize(("sent", "code"), [(signal.SIGINT, 130)])
@pytest.mark.parametrize("mode", ["--no-merge", ""])
def test_signal_during_an_answering_probe_stops_verify_before_bronze_and_silver(
    tmp_path: Path, mode: str, sent: signal.Signals, code: int
) -> None:
    # The probe would pass, and the next step is the first Kafka call, then the merge: a signal that
    # only the script gets must stop it where it is, not after the probe and one more step.
    result, calls, seconds, _ = run_verify(
        tmp_path, mode, trino="slow", interrupt=sent, TRINO_PROBE_WAIT="10", VERIFY_WAIT="0"
    )

    assert result.returncode == code, result.stderr
    assert "verify interrupted" in result.stderr
    assert "bronze did not catch up" not in result.stderr
    assert seconds < 2 + 2 + 3
    assert not any(" exec -T kafka " in call or "spark-silver" in call for call in calls)


def test_catalog_probe_names_catalog_lake_and_passes_on_a_healthy_stack(tmp_path: Path) -> None:
    result, calls, _, _ = run_verify(tmp_path, "--no-merge", trino="up", VERIFY_WAIT="0")

    schema_calls = [call for call in calls if "show schemas" in call]
    assert len(schema_calls) == 1
    assert "--catalog lake" in schema_calls[0]
    assert "Catalog must be specified" not in result.stderr
    assert "catalog lake" not in result.stderr


def test_answering_trino_and_catalog_let_verify_go_on_to_bronze(tmp_path: Path) -> None:
    result, calls, _, _ = run_verify(tmp_path, "--no-merge", trino="up", VERIFY_WAIT="0")

    assert "Trino does not answer" not in result.stderr
    assert "Trino probe failed" not in result.stderr
    assert result.returncode == 1
    assert "verify failed: bronze did not catch up with Kafka in 0 s" in result.stderr
    probe = next(i for i, call in enumerate(calls) if call.endswith(PROBE))
    lake = next(i for i, call in enumerate(calls) if call.endswith(LAKE_PROBE))
    kafka = next(i for i, call in enumerate(calls) if " exec -T kafka " in call)
    store = next(i for i, call in enumerate(calls) if STORE_PROBE in call)
    assert probe < lake < store < kafka


def test_verify_script_table_literal_is_the_seven_contracts() -> None:
    text = (REPO / "scripts" / "verify.sh").read_text()
    literal = re.search(r"source_table in \(([^)]*)\)", text)
    assert literal is not None
    tables = re.findall(r"'([a-z_]+)'", literal.group(1))
    contracts = sorted(p.stem for p in (REPO / "contracts" / "silver").glob("*.json"))
    assert sorted(tables) == contracts
    assert re.search(rf'\[ "\$tables" = {len(contracts)} \]', text)
    assert f"of the {len(contracts)} source tables" in text


@pytest.mark.parametrize("mode", ["--no-merge", ""])
def test_storage_down_with_catalog_alive_refuses_with_exit_2_and_names_the_storage(
    tmp_path: Path, mode: str
) -> None:
    result, calls, seconds, _ = run_verify(tmp_path, mode, store="storedown")

    assert result.returncode == 2, result.stderr
    assert (
        "verify failed: Trino and catalog lake answer, but the object store (MinIO) fails:"
        in result.stderr
    )
    assert "Could not resolve host: minio" in result.stderr
    assert "bronze did not catch up" not in result.stderr
    assert any(call.endswith(LAKE_PROBE) for call in calls)
    assert any(STORE_PROBE in call for call in calls)
    assert not any(" exec -T kafka " in call for call in calls)
    assert seconds < HARD_LIMIT / 2


@pytest.mark.parametrize("mode", ["--no-merge", ""])
def test_storage_that_hangs_refuses_after_the_probe_limit(tmp_path: Path, mode: str) -> None:
    result, calls, seconds, left = run_verify(tmp_path, mode, store="hang", TRINO_PROBE_WAIT="1")

    assert result.returncode == 2, result.stderr
    assert "but the object store (MinIO) does not answer within 1 s" in result.stderr
    assert "bronze did not catch up" not in result.stderr
    assert seconds < 1 + 2
    assert not any(" exec -T kafka " in call for call in calls)
    assert not left, f"the probe left processes behind: {left}"


def test_storage_that_ignores_sigterm_is_killed_after_the_grace_period(tmp_path: Path) -> None:
    # timeout answers 137, still "does not answer", not "fails".
    result, calls, seconds, _ = run_verify(
        tmp_path, "--no-merge", store="stubborn", TRINO_PROBE_WAIT="1"
    )

    assert result.returncode == 2, result.stderr
    assert "but the object store (MinIO) does not answer within 1 s" in result.stderr
    assert "MinIO) fails" not in result.stderr
    assert any(STORE_PROBE in call for call in calls)
    assert seconds < 6


@pytest.mark.parametrize("mode", ["--no-merge", ""])
def test_ctrl_c_during_the_catalog_probe_does_not_start_the_storage_probe(
    tmp_path: Path, mode: str
) -> None:
    result, calls, _, _ = run_verify(
        tmp_path, mode, trino="slow", interrupt=signal.SIGINT, TRINO_PROBE_WAIT="3", VERIFY_WAIT="0"
    )

    assert result.returncode == 130, result.stderr
    assert not any(STORE_PROBE in call for call in calls)


def test_ctrl_c_between_the_catalog_and_the_storage_probe_does_not_start_the_storage_probe(
    tmp_path: Path,
) -> None:
    # The signal comes while the second probe runs: the trap must fire before the third starts.
    result, calls, _, _ = run_verify(
        tmp_path,
        "--no-merge",
        lake="slow",
        interrupt=signal.SIGINT,
        wait_for=LAKE_PROBE,
        TRINO_PROBE_WAIT="5",
        VERIFY_WAIT="0",
    )

    assert result.returncode == 130, result.stderr
    assert "verify interrupted" in result.stderr
    assert any(call.endswith(LAKE_PROBE) for call in calls)
    assert not any(STORE_PROBE in call for call in calls)


def test_storage_probe_gives_curl_the_limit_of_the_probe(tmp_path: Path) -> None:
    # Without its own limit curl in the container would hang on after timeout killed the exec.
    run_verify(tmp_path, "--no-merge", VERIFY_WAIT="0", TRINO_PROBE_WAIT="7")

    # The replayer check also calls curl; only the health check is of interest here.
    curl_calls = [
        line for line in (tmp_path / "curl-calls").read_text().splitlines() if "minio" in line
    ]
    assert curl_calls == ["-sfS -o /dev/null -m 7 http://in-container-minio:9000/minio/health/live"]


def test_storage_probe_is_a_health_check_in_the_trino_container_not_a_table_query(
    tmp_path: Path,
) -> None:
    # Trino caches table metadata, so any query on a table can answer with MinIO down.
    _, calls, _, _ = run_verify(tmp_path, "--no-merge", VERIFY_WAIT="0")

    probes = [call for call in calls if " exec -T trino " in call]
    assert len(probes) == 3
    assert STORE_PROBE in probes[2]
    assert "select" not in probes[2]
    assert "minio/health" in probes[2]
    # Expanded by the shell in the container, from the endpoint of its catalog, not on the host.
    assert "$S3_ENDPOINT" in probes[2]
    assert "host-side-minio" not in probes[2]
