from typing import Any

import psycopg
import pytest
from replayer import __main__ as cli
from replayer import replay, server, state
from replayer.settings import Settings


class FakeCursor:
    def __init__(self, conn: "FakeConn") -> None:
        self.conn = conn

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, *args: Any) -> None:
        self.conn.executed.append(sql)
        if self.conn.missing:
            raise psycopg.errors.UndefinedTable("relation replay.schedule does not exist")

    def fetchone(self) -> tuple[int]:
        return (7,)


class FakeConn:
    def __init__(self, missing: bool = False) -> None:
        self.missing = missing
        self.executed: list[str] = []
        self.commits = 0

    def __enter__(self) -> "FakeConn":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1


def isolated_settings() -> Settings:
    """No `.env` of the repo root: the environment alone decides."""
    return Settings(_env_file=None)  # type: ignore[call-arg]


def fake_state() -> state.State:
    from datetime import datetime, timedelta

    now = datetime(2026, 7, 1, 12, 0)
    return state.State(
        shift=timedelta(days=3),
        cutoff_ts=now,
        horizon_ts=now,
        virtual_now=now,
        events_emitted=5,
        started_at=None,
    )


def patch(monkeypatch: pytest.MonkeyPatch, conn: FakeConn, current: state.State | None) -> None:
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(state, "read", lambda c: current)

    def forbidden(c: object) -> None:
        raise AssertionError("status must not run DDL")

    monkeypatch.setattr(state, "ensure_schema", forbidden)


def test_status_runs_no_ddl_and_keeps_its_keys(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = FakeConn()
    patch(monkeypatch, conn, fake_state())

    assert cli.cmd_status(isolated_settings()) == 0

    assert conn.executed
    assert all(sql.strip().lower().startswith("select") for sql in conn.executed), conn.executed
    out = capsys.readouterr().out
    for key in (
        "cutoff",
        "virtual_now",
        "horizon",
        "shift_days",
        "events_emitted",
        "events_pending",
        "started_at",
        "finished",
    ):
        assert f'"{key}"' in out
    assert '"events_pending": 7' in out
    assert conn.commits == 0


def test_status_without_replay_schema_says_so_and_does_not_raise(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def missing(c: object) -> None:
        raise psycopg.errors.UndefinedTable("relation replay.state does not exist")

    patch(monkeypatch, FakeConn(), None)
    monkeypatch.setattr(state, "read", missing)

    assert cli.cmd_status(isolated_settings()) == 1
    assert "no replay state; run `make replay-load`" in capsys.readouterr().out


def test_status_with_missing_schedule_table_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    patch(monkeypatch, FakeConn(missing=True), fake_state())

    assert cli.cmd_status(isolated_settings()) == 1
    assert "no replay state; run `make replay-load`" in capsys.readouterr().out


def test_http_server_listens_on_loopback_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HTTP_HOST", raising=False)
    settings = isolated_settings()
    srv = server.serve(0, dict, settings.http_host)
    try:
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        srv.shutdown()
        srv.server_close()


def test_http_host_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_HOST", "0.0.0.0")
    settings = isolated_settings()
    srv = server.serve(0, dict, settings.http_host)
    try:
        assert srv.server_address[0] == "0.0.0.0"
    finally:
        srv.shutdown()
        srv.server_close()


def test_run_hands_the_configured_host_to_the_server(monkeypatch: pytest.MonkeyPatch) -> None:
    served: list[tuple[int, str]] = []

    class StopRunError(Exception):
        pass

    def fake_serve(port: int, status: object, host: str) -> None:
        served.append((port, host))
        raise StopRunError

    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: FakeConn())
    monkeypatch.setattr(state, "ensure_schema", lambda c: None)
    monkeypatch.setattr(server, "serve", fake_serve)
    monkeypatch.setenv("HTTP_HOST", "0.0.0.0")
    settings = isolated_settings()

    with pytest.raises(StopRunError):
        replay.run(settings)

    assert served == [(settings.http_port, "0.0.0.0")]
