import base64
import stat
import string
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.make_env import render

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


def test_existing_values_are_not_changed_and_a_missing_key_is_appended(workdir: Path) -> None:
    existing = "# mine\nOLTP_PASSWORD=keep_me\nS3_SECRET_KEY=keep_too\nCOMPOSE_PROJECT_NAME=x"
    (workdir / ".env").write_text(existing)
    (workdir / ".env").chmod(0o640)

    result = run(workdir)

    assert result.returncode == 0, result.stderr
    text = (workdir / ".env").read_text()
    assert text.startswith(existing + "\n")
    env = parse(text)
    assert env["OLTP_PASSWORD"] == "keep_me"
    assert env["COMPOSE_PROJECT_NAME"] == "x"
    assert len(env["AIRFLOW_FERNET_KEY"]) > 24 and env["AIRFLOW_FERNET_KEY"] != "change_me"
    assert "REPLAY_SCHEMA_EVOLUTION_AT=  # empty = never" in text
    assert "2 missing keys appended" in result.stdout
    assert "keep_me" not in result.stdout
    assert stat.S_IMODE((workdir / ".env").stat().st_mode) == 0o600


def test_a_second_run_appends_nothing(workdir: Path) -> None:
    (workdir / ".env").write_text("OLTP_PASSWORD=keep_me\n")
    run(workdir)
    first = (workdir / ".env").read_text()

    result = run(workdir)

    assert result.returncode == 0, result.stderr
    assert (workdir / ".env").read_text() == first
    assert "0 missing keys appended" in result.stdout


def test_a_complete_env_stays_byte_identical(workdir: Path) -> None:
    run(workdir)
    first = (workdir / ".env").read_bytes()

    run(workdir)

    assert (workdir / ".env").read_bytes() == first


def test_airflow_fernet_key_is_32_urlsafe_base64_bytes() -> None:
    text, _ = render("AIRFLOW_FERNET_KEY=change_me\n")

    key = parse(text)["AIRFLOW_FERNET_KEY"]
    assert len(base64.urlsafe_b64decode(key)) == 32


def test_other_secrets_keep_the_token_urlsafe_format() -> None:
    text, generated = render("OLTP_PASSWORD=change_me\nAIRFLOW_JWT_SECRET=change_me\n")

    env = parse(text)
    assert generated == 2
    for key in ("OLTP_PASSWORD", "AIRFLOW_JWT_SECRET"):
        assert len(env[key]) == 32
        assert set(env[key]) <= set(string.ascii_letters + string.digits + "-_")


def test_keys_are_compared_after_strip_and_export_prefix(workdir: Path) -> None:
    (workdir / ".env").write_text(
        "export OLTP_PASSWORD=keep_me\n  S3_SECRET_KEY = keep_too\nAIRFLOW_FERNET_KEY=k\n"
    )

    run(workdir)

    text = (workdir / ".env").read_text()
    assert text.count("OLTP_PASSWORD") == 1
    assert text.count("S3_SECRET_KEY") == 1


def test_env_is_made_private_before_a_secret_is_appended(
    workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import make_env

    (workdir / ".env").write_text("OLTP_PASSWORD=keep_me\n")
    (workdir / ".env").chmod(0o644)
    monkeypatch.chdir(workdir)
    modes: list[int] = []
    real_open: Any = Path.open

    def spy(self: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if mode == "a":
            modes.append(stat.S_IMODE(self.stat().st_mode))
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spy)

    assert make_env.append_missing() == 0
    assert modes == [0o600]
