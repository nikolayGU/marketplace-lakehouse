import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "make_env.py"


def run(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=cwd, capture_output=True, text=True, check=False
    )


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    (tmp_path / ".env.example").write_text(
        "# comment\n"
        "COMPOSE_PROJECT_NAME=lakehouse\n"
        "OLTP_PASSWORD=change_me\n"
        "S3_SECRET_KEY=change_me\n"
        "REPLAY_SCHEMA_EVOLUTION_AT=  # empty = never\n"
        "AIRFLOW_FERNET_KEY=change_me\n"
    )
    return tmp_path


def parse(env_text: str) -> dict[str, str]:
    pairs = (line.partition("=") for line in env_text.splitlines() if "=" in line)
    return {key: value for key, _, value in pairs}


def test_replaces_every_placeholder_with_distinct_secrets(workdir: Path) -> None:
    result = run(workdir)

    assert result.returncode == 0, result.stderr
    env = parse((workdir / ".env").read_text())
    secrets = [env["OLTP_PASSWORD"], env["S3_SECRET_KEY"], env["AIRFLOW_FERNET_KEY"]]
    assert "change_me" not in secrets
    assert all(len(s) >= 24 for s in secrets)
    assert len(set(secrets)) == 3
    assert "3 secrets generated" in result.stdout


def test_keeps_non_secret_lines_verbatim(workdir: Path) -> None:
    run(workdir)

    lines = (workdir / ".env").read_text().splitlines()
    assert lines[0] == "# comment"
    assert lines[1] == "COMPOSE_PROJECT_NAME=lakehouse"
    assert lines[4] == "REPLAY_SCHEMA_EVOLUTION_AT=  # empty = never"


def test_env_is_owner_read_write_only(workdir: Path) -> None:
    run(workdir)

    mode = stat.S_IMODE((workdir / ".env").stat().st_mode)
    assert mode == 0o600


def test_does_not_overwrite_existing_env(workdir: Path) -> None:
    (workdir / ".env").write_text("OLTP_PASSWORD=keep_me\n")

    result = run(workdir)

    assert result.returncode == 1
    assert "not overwriting" in result.stderr
    assert (workdir / ".env").read_text() == "OLTP_PASSWORD=keep_me\n"
