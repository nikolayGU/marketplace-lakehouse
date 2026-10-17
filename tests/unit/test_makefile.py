import os
import subprocess
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
