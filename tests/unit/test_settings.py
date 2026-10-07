from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from replayer.settings import Settings


@pytest.fixture(autouse=True)
def without_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Settings reads `.env` from the working directory: the developer's own file must not leak in.
    monkeypatch.chdir(tmp_path)


def test_explicit_dsn_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLTP_DSN", "postgresql://u:p@postgres-oltp:5432/shop")

    assert Settings().dsn == "postgresql://u:p@postgres-oltp:5432/shop"


def test_dsn_is_assembled_from_parts_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLTP_DSN", raising=False)
    monkeypatch.setenv("OLTP_USER", "shop")
    monkeypatch.setenv("OLTP_PASSWORD", "secret")
    monkeypatch.setenv("OLTP_DB", "shop")
    monkeypatch.setenv("BIND_IP", "127.0.0.1")

    assert Settings().dsn == "postgresql://shop:secret@127.0.0.1:5432/shop"


def test_empty_schema_evolution_mark_means_never(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLAY_SCHEMA_EVOLUTION_AT", "")

    assert Settings().replay_schema_evolution_at is None


def test_schema_evolution_mark_is_a_virtual_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLAY_SCHEMA_EVOLUTION_AT", "2026-07-01T12:00:00")

    assert Settings().replay_schema_evolution_at == datetime(2026, 7, 1, 12, 0)


def test_unparseable_schema_evolution_mark_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # What an empty value followed by an inline comment turns into in both dotenv parsers.
    monkeypatch.setenv("REPLAY_SCHEMA_EVOLUTION_AT", "# empty = never")

    with pytest.raises(ValidationError, match="replay_schema_evolution_at"):
        Settings()
