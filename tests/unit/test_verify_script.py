"""The first step of scripts/verify.sh after the replayer check: Trino answers. It runs the real
script and the real lib.sh in a temporary root, with `docker` and `curl` replaced by fakes first in
PATH, so no container is touched. Without the probe an unreachable Trino made `bronze_caught_up`
fail on every try, and verify waited VERIFY_WAIT (900 s) and blamed Kafka."""

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# What every run must stay under: the old code waited VERIFY_WAIT, here 600 s.
HARD_LIMIT = 10

# Every call is logged. $TRINO decides how `compose ... exec ... trino` answers; a Kafka call
# fails, so a run that gets past the probe ends at "bronze did not catch up" without a stack.
# `hang` and `stubborn` start a child that outlives its parent unless the whole group is killed,
# and log its pid; `stubborn` also ignores SIGTERM, so only the kill after the grace period ends it.
# `slow` answers after 2 s.
FAKE_DOCKER = """#!/usr/bin/env bash
echo "$*" >>"$DOCKER_CALLS"
case "$*" in
  *" exec -T trino "*)
    case "$TRINO" in
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
FAKE_CURL = "#!/usr/bin/env bash\nexit 7\n"

PROBE = "exec -T trino trino --execute select 1"


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
    trino: str,
    interrupt: signal.Signals | None = None,
    **env: str,
) -> tuple[subprocess.CompletedProcess[str], list[str], float, list[int]]:
    # interrupt: sent to the bash process alone once the probe has started, as a terminal sends it
    # to the foreground group, where timeout is not: it runs the probe in a group of its own.
    root = tmp_path / "root"
    (root / "scripts" / "chaos").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "verify.sh", root / "scripts" / "verify.sh")
    shutil.copy(REPO / "scripts" / "chaos" / "lib.sh", root / "scripts" / "chaos" / "lib.sh")
    (root / ".env").write_text("OLTP_USER=user\nOLTP_DB=db\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("docker", FAKE_DOCKER), ("curl", FAKE_CURL)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    calls = tmp_path / "docker-calls"
    calls.touch()
    pids = tmp_path / "pids"
    pids.touch()
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
            "PIDS": str(pids),
            "TMPDIR": str(scratch),
            "TRINO": trino,
            "VERIFY_WAIT": "600",
            **env,
        },
    )
    if interrupt is not None:
        while not any(line.endswith(PROBE) for line in calls.read_text().splitlines()):
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


def test_answering_trino_lets_verify_go_on_to_bronze(tmp_path: Path) -> None:
    result, calls, _, _ = run_verify(tmp_path, "--no-merge", trino="up", VERIFY_WAIT="0")

    assert "Trino does not answer" not in result.stderr
    assert "Trino probe failed" not in result.stderr
    assert result.returncode == 1
    assert "verify failed: bronze did not catch up with Kafka in 0 s" in result.stderr
    probe = next(i for i, call in enumerate(calls) if call.endswith(PROBE))
    kafka = next(i for i, call in enumerate(calls) if " exec -T kafka " in call)
    assert probe < kafka
