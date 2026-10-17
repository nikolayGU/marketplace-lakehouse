"""SQL for `reconcile` in `scripts/chaos/lib.sh`, derived from `contracts/silver/*.json`.

Prints one line per contract: `<table>\\t<postgres query>\\t<trino query>`. Each query returns one
text value, `<rows> <md5 of the sorted keys> [<sum> ...]`, and the two values are equal when
silver's live rows match the source: same count, same set of primary keys, and the same sum of
every decimal column at its contract scale. Counts alone miss a lost row that an undeleted one
offsets.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

DECIMAL = re.compile(r"decimal\(\s*\d+\s*,\s*(\d+)\s*\)")


def queries(contract: dict[str, Any]) -> tuple[str, str, str]:
    source = contract["x-source-table"]
    if source.count(".") != 1:
        raise ValueError(f"x-source-table {source!r} is not schema.table")
    table = source.split(".")[1]
    keys: list[str] = contract.get("x-primary-key") or []
    if not keys:
        raise ValueError(f"{source}: no x-primary-key")
    properties: dict[str, Any] = contract["properties"]
    for key in keys:
        if key not in properties:
            raise ValueError(f"{source}: key {key!r} is not a property")
    decimals = [
        (name, int(match.group(1)))
        for name, spec in properties.items()
        if (match := DECIMAL.fullmatch(spec["x-silver-type"]))
    ]
    columns = "".join(f", {name}" for name, _ in decimals)

    # Keys are joined with ':' and sorted bytewise on both sides: Postgres with the C collation,
    # Trino by its varchar order, which compares UTF-8 bytes.
    pg_key = keys[0] + "::text" if len(keys) == 1 else _concat([f"{k}::text" for k in keys])
    pg_values = [
        "count(*)",
        "md5(coalesce(string_agg(k, ',' order by k collate \"C\"), ''))",
        *[f"cast(coalesce(sum({n}), 0) as numeric(38, {s}))" for n, s in decimals],
    ]
    postgres = (
        f"with src as (select {pg_key} as k{columns} from {source}) "
        f"select concat_ws(' ', {', '.join(pg_values)}) from src"
    )

    trino_keys = [f"cast({k} as varchar)" for k in keys]
    trino_key = trino_keys[0] if len(keys) == 1 else _concat(trino_keys)
    trino_values = [
        "cast(count(*) as varchar)",
        "lower(to_hex(md5(to_utf8(coalesce(array_join(array_agg(k order by k), ','), '')))))",
        *[f"cast(cast(coalesce(sum({n}), 0) as decimal(38, {s})) as varchar)" for n, s in decimals],
    ]
    trino = (
        f"with live as (select {trino_key} as k{columns} from silver.{table} "
        f"where not _is_deleted) select concat_ws(' ', {', '.join(trino_values)}) from live"
    )
    return table, postgres, trino


def _concat(parts: list[str]) -> str:
    return f"concat_ws(':', {', '.join(parts)})"


def main() -> None:
    contracts_dir = Path(sys.argv[1])
    for path in sorted(contracts_dir.glob("*.json")):
        print("\t".join(queries(json.loads(path.read_text()))))


if __name__ == "__main__":
    main()
