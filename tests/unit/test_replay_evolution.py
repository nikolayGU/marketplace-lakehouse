from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from replayer import migrations, replay, state
from replayer.replay import (
    EVOLUTION,
    INSERT_ORDER,
    INSERT_ORDER_WITH_CHANNEL,
    Conn,
    Replayer,
    evolution_due,
)
from replayer.settings import Settings
from replayer.state import Row, State

AT = datetime(2026, 7, 1, 12, 0)
CLOCK = State(
    shift=timedelta(days=2900),
    cutoff_ts=datetime(2026, 1, 1),
    horizon_ts=datetime(2027, 1, 1),
    virtual_now=datetime(2026, 9, 1),
    events_emitted=0,
    started_at=None,
)
COLUMN = ("orders", "sales_channel")
INSERTS = {INSERT_ORDER: "INSERT_ORDER", INSERT_ORDER_WITH_CHANNEL: "INSERT_ORDER_WITH_CHANNEL"}


def test_not_configured_never_fires() -> None:
    assert not evolution_due(None, datetime(2030, 1, 1), applied=False)


def test_fires_once_the_virtual_clock_reaches_the_mark() -> None:
    assert not evolution_due(AT, datetime(2026, 7, 1, 11, 59), applied=False)
    assert evolution_due(AT, AT, applied=False)


def test_mark_already_behind_the_clock_fires_on_the_first_step() -> None:
    assert evolution_due(AT, datetime(2026, 9, 1), applied=False)


def test_applied_never_fires_again() -> None:
    assert not evolution_due(AT, datetime(2026, 9, 1), applied=True)


def test_migration_lives_outside_make_migrate() -> None:
    assert EVOLUTION.is_file()
    assert EVOLUTION.parent.name == "evolution"
    todo = migrations.pending(cast(Conn, FakeConn()), migrations.migrations_dir())
    assert EVOLUTION not in todo
    assert any(p.name == "001_schema.sql" for p in todo)


@pytest.fixture(autouse=True)
def without_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Settings reads `.env` from the working directory: the developer's own file must not leak in.
    monkeypatch.chdir(tmp_path)


class FakeConn:
    """Records every statement; `due` is what the next CLAIM hands back."""

    def __init__(self) -> None:
        self.sql: list[str] = []
        self.due: list[Row] = []

    def cursor(self) -> "FakeCursor":
        return FakeCursor(self)

    def commit(self) -> None:
        pass


class FakeCursor:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def execute(self, query: str, params: object = None) -> None:
        self.conn.sql.append(query)

    def fetchall(self) -> list[Row]:
        rows, self.conn.due = self.conn.due, []
        return rows

    def fetchone(self) -> None:
        return None


def wire(monkeypatch: pytest.MonkeyPatch, columns: set[tuple[str, str]]) -> list[str]:
    """Stub the database edges of `Replayer`; the returned list collects applied file names."""
    applied: list[str] = []
    monkeypatch.setattr(state, "read", lambda conn: CLOCK)
    monkeypatch.setattr(
        replay, "has_column", lambda conn, table, column: (table, column) in columns
    )
    monkeypatch.setattr(migrations, "apply", lambda conn, path: applied.append(path.name))
    return applied


def order_insert(order_id: str) -> Row:
    return (1, CLOCK.virtual_now, "order_insert", order_id, None, False)


def order_inserts(conn: FakeConn) -> list[str]:
    return [INSERTS[sql] for sql in conn.sql if sql in INSERTS]


def test_mark_behind_the_clock_applies_once_then_orders_carry_a_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    applied = wire(monkeypatch, columns=set())
    conn = FakeConn()
    replayer = Replayer(Settings(replay_schema_evolution_at=AT), cast(Conn, conn))

    replayer.step()
    assert applied == [EVOLUTION.name]

    conn.due.append(order_insert("o1"))
    replayer.step()
    assert applied == [EVOLUTION.name]
    assert order_inserts(conn) == ["INSERT_ORDER_WITH_CHANNEL"]


def test_restart_with_the_column_present_does_not_alter_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A second ALTER fails on "column already exists", and the container would crash-loop.
    applied = wire(monkeypatch, columns={COLUMN})
    conn = FakeConn()
    conn.due.append(order_insert("o1"))

    Replayer(Settings(replay_schema_evolution_at=AT), cast(Conn, conn)).step()

    assert applied == []
    assert order_inserts(conn) == ["INSERT_ORDER_WITH_CHANNEL"]


@pytest.mark.parametrize("at", [None, datetime(2026, 12, 1)], ids=["no-mark", "mark-ahead"])
def test_without_a_due_mark_orders_keep_the_original_insert(
    monkeypatch: pytest.MonkeyPatch, at: datetime | None
) -> None:
    applied = wire(monkeypatch, columns=set())
    conn = FakeConn()
    conn.due.append(order_insert("o1"))

    Replayer(Settings(replay_schema_evolution_at=at), cast(Conn, conn)).step()

    assert applied == []
    assert order_inserts(conn) == ["INSERT_ORDER"]
