import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def make(*args: str) -> subprocess.CompletedProcess[str]:
    # COMPOSE=echo: a target that does not refuse prints its compose command instead of starting
    # containers, so no run of this file can start the replayer. make also reads PROFILE, SECONDS
    # and SPEED from the environment; a developer's shell must not decide the outcome.
    env = {k: v for k, v in os.environ.items() if k not in {"PROFILE", "SECONDS", "SPEED"}}
    return subprocess.run(
        ["make", "--no-print-directory", "-C", str(REPO), "COMPOSE=echo docker compose", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@pytest.mark.parametrize("profile", ["core", "core,query", "query,core"])
def test_up_refuses_any_profile_with_core(profile: str) -> None:
    result = make("up", f"PROFILE={profile}")

    assert result.returncode == 2
    assert "make start" in result.stderr


def test_up_without_profile_means_core_and_refuses() -> None:
    result = make("up")

    assert result.returncode == 2
    assert "make start" in result.stderr


@pytest.mark.parametrize("args", [(), ("SECONDS=abc",), ("SECONDS=60", "SPEED=0")])
def test_replay_burst_refuses_without_positive_seconds_and_speed(args: tuple[str, ...]) -> None:
    result = make("replay-burst", *args)

    assert result.returncode == 2
    assert "usage: make replay-burst" in result.stderr


def test_silver_refuses_while_the_scheduler_runs() -> None:
    # COMPOSE=echo makes `ps -q airflow-scheduler` print something, as a running scheduler would.
    result = make("silver")

    assert result.returncode == 2
    assert "airflow-scheduler" in result.stderr
    assert "spark-silver" not in result.stdout


def test_silver_refuses_when_it_cannot_tell_whether_the_scheduler_runs() -> None:
    # A failing `docker compose ps` must not read as "no scheduler": two writers on one checkpoint.
    result = make("silver", "COMPOSE=false")

    assert result.returncode == 2
    assert "cannot tell" in result.stderr


def test_silver_runs_the_merge_when_no_scheduler_runs() -> None:
    # COMPOSE=true: `ps -q` prints nothing and succeeds, the merge command runs (as `true`).
    # DOCKER=true: no merge container is found, whatever the host's Docker holds.
    assert make("silver", "COMPOSE=true", "DOCKER=true").returncode == 0


# A fake `docker` first in PATH. `compose ...` succeeds and prints nothing (no scheduler, and the
# merge "runs"); `ps` lists the Airflow merge container with $MERGE_STATUS if a filter names it.
FAKE_DOCKER = """#!/usr/bin/env bash
echo "$*" >>"$DOCKER_CALLS"
case "$1" in
  compose) exit 0 ;;
  ps)
    [ "$PS_FAILS" = 1 ] && exit 1
    case "$*" in
      *"$MERGE_CONTAINER"*) [ -n "$MERGE_STATUS" ] && echo "$MERGE_CONTAINER: $MERGE_STATUS" ;;
    esac
    exit 0 ;;
esac
"""


def merge_container_name() -> str:
    # The container silver_upsert's merge task starts: what `make silver` has to look for.
    source = (REPO / "airflow" / "dags" / "silver_upsert.py").read_text()
    found = re.search(r'container_name="([^"]+)"', source)
    assert found is not None, "merge has no container_name"
    return found.group(1)


def run_with_fake_docker(
    tmp_path: Path, argv: list[str], status: str = "", ps_fails: bool = False
) -> tuple[subprocess.CompletedProcess[str], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    calls = tmp_path / "docker-calls"
    calls.touch()
    skipped = {"PROFILE", "SECONDS", "SPEED", "COMPOSE", "DOCKER"}
    env = {k: v for k, v in os.environ.items() if k not in skipped}
    env |= {
        "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
        "DOCKER_CALLS": str(calls),
        "MERGE_CONTAINER": merge_container_name(),
        "MERGE_STATUS": status,
        "PS_FAILS": "1" if ps_fails else "0",
    }
    result = subprocess.run(argv, capture_output=True, text=True, env=env, check=False)
    return result, calls.read_text()


def make_silver(
    tmp_path: Path, status: str = "", ps_fails: bool = False
) -> tuple[subprocess.CompletedProcess[str], str]:
    argv = ["make", "--no-print-directory", "-C", str(REPO), "silver"]
    return run_with_fake_docker(tmp_path, argv, status, ps_fails)


def run_silver(
    tmp_path: Path, status: str = "", ps_fails: bool = False
) -> tuple[subprocess.CompletedProcess[str], str]:
    # run_silver of scripts/chaos/lib.sh, which make verify and the chaos scripts call, in a root
    # of its own so that it runs this Makefile.
    root = tmp_path / "root"
    (root / "scripts" / "chaos").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "chaos" / "lib.sh", root / "scripts" / "chaos" / "lib.sh")
    shutil.copy(REPO / "Makefile", root / "Makefile")
    (root / ".env").write_text("OLTP_USER=user\n")
    argv = ["bash", "-c", f'. "{root}/scripts/chaos/lib.sh"; run_silver']
    return run_with_fake_docker(tmp_path, argv, status, ps_fails)


StartSilver = Callable[..., tuple[subprocess.CompletedProcess[str], str]]


@pytest.mark.parametrize("status", ["Up 3 minutes", "Exited (137) 2 minutes ago", "Created"])
@pytest.mark.parametrize("start", [make_silver, run_silver])
def test_silver_refuses_while_the_merge_container_of_airflow_exists(
    tmp_path: Path, start: StartSilver, status: str
) -> None:
    # The scheduler may be stopped in the middle of a merge: the container goes on writing the
    # checkpoint, and a second writer from here would corrupt it. Any status counts, an Exited
    # one is a leftover that blocks Airflow's merge as well and is removed by hand.
    result, calls = start(tmp_path, status=status)

    assert result.returncode != 0
    name = merge_container_name()
    assert f"{name}: {status}" in result.stderr
    assert "wait" in result.stderr and f"docker rm {name}" in result.stderr
    assert "spark-silver" not in calls


@pytest.mark.parametrize("start", [make_silver, run_silver])
def test_silver_refuses_when_it_cannot_tell_whether_the_merge_container_exists(
    tmp_path: Path, start: StartSilver
) -> None:
    result, calls = start(tmp_path, ps_fails=True)

    assert result.returncode != 0
    assert "cannot tell" in result.stderr
    assert "spark-silver" not in calls


@pytest.mark.parametrize("start", [make_silver, run_silver])
def test_silver_runs_the_merge_when_the_merge_container_of_airflow_is_gone(
    tmp_path: Path, start: StartSilver
) -> None:
    result, calls = start(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "run --rm --no-deps spark-silver" in calls


def _locked(package: str) -> str:
    lock = (REPO / "uv.lock").read_text()
    block = lock.split(f'name = "{package}"\nversion = "', 1)[1]
    return block.split('"', 1)[0]


def test_spark_tests_run_in_the_image_given_and_fail_on_skips() -> None:
    result = make("-n", "test-spark", "SPARK_IMAGE=lakehouse/spark:ci")

    assert "lakehouse/spark:ci" in result.stdout
    assert "-p no:skipping" in result.stdout
    assert "FAIL_ON_SKIP=1" in result.stdout


SKIPPING = """
import pytest

pytestmark = pytest.mark.parametrize("n", [1])


def test_calls_skip(n):
    pytest.skip("no JVM")


@pytest.fixture
def jvm():
    pytest.skip("no JVM")


def test_fixture_skips(n, jvm):
    pass


def test_runs(n):
    pass
"""


@pytest.mark.parametrize(
    ("fail_on_skip", "code", "line"),
    [("1", 1, "1 failed, 1 passed, 1 error"), ("", 0, "1 passed, 2 skipped")],
)
def test_fail_on_skip_fails_every_kind_of_skip(
    tmp_path: Path, fail_on_skip: str, code: int, line: str
) -> None:
    (tmp_path / "test_skipping.py").write_text(SKIPPING)
    env = {**os.environ, "PYTHONPATH": str(REPO / "tests" / "unit"), "FAIL_ON_SKIP": fail_on_skip}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "conftest", "-p", "no:cacheprovider", "."],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == code, result.stdout
    assert line in result.stdout


def test_spark_test_pins_follow_the_lock_file() -> None:
    # The image installs its own pytest and jsonschema; a drift from uv.lock would make CI test
    # something other than the host does.
    result = make("-n", "test-spark")

    assert f"pytest=={_locked('pytest')}" in result.stdout
    assert f"jsonschema=={_locked('jsonschema')}" in result.stdout
