import os
import subprocess
import sys
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
    assert make("silver", "COMPOSE=true").returncode == 0


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
