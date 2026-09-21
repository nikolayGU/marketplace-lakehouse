"""Apply numbered SQL migrations from `oltp/migrations` exactly once.

Bookkeeping lives in `public.schema_migrations`, outside schema `shop`, so it never reaches the
CDC publication. Each file runs in its own transaction: a failure leaves earlier files applied
and the broken one not recorded.
"""

import os
import sys
from pathlib import Path

import psycopg

from replayer.settings import Settings

BOOKKEEPING = """
create table if not exists public.schema_migrations (
    filename text primary key,
    applied_at timestamptz not null default now()
)
"""


def migrations_dir() -> Path:
    override = os.environ.get("MIGRATIONS_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "migrations"


def pending(conn: psycopg.Connection[tuple[object, ...]], directory: Path) -> list[Path]:
    with conn.cursor() as cur:
        cur.execute(BOOKKEEPING)
        cur.execute("select filename from public.schema_migrations")
        applied = {row[0] for row in cur.fetchall()}
    conn.commit()
    return [p for p in sorted(directory.glob("*.sql")) if p.name not in applied]


def apply(conn: psycopg.Connection[tuple[object, ...]], path: Path) -> None:
    with conn.cursor() as cur:
        cur.execute(path.read_text())
        cur.execute("insert into public.schema_migrations (filename) values (%s)", (path.name,))
    conn.commit()


def main() -> int:
    directory = migrations_dir()
    if not directory.is_dir():
        print(f"no migrations directory at {directory}", file=sys.stderr)
        return 1
    with psycopg.connect(Settings().dsn) as conn:
        todo = pending(conn, directory)
        if not todo:
            print("schema up to date, nothing to apply")
            return 0
        for path in todo:
            apply(conn, path)
            print(f"applied {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
