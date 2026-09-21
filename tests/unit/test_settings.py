import pytest
from replayer.settings import Settings


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
