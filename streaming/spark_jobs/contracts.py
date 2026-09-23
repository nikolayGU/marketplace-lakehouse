"""Silver table contracts, `contracts/silver/<table>.json`, as Spark schemas and casts.

A contract describes each column twice: `type` is the JSON type Debezium writes into
before/after, `x-silver-type` is the column type in silver. Silver parses the payload with the
wire types and casts afterwards, so a value that does not fit becomes null instead of failing
the batch.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyspark.sql import Column
from pyspark.sql import functions as F
from pyspark.sql.types import DataType, DoubleType, LongType, StringType, StructField, StructType

WIRE_TYPES: dict[str, DataType] = {
    "string": StringType(),
    "integer": LongType(),
    "number": DoubleType(),
}
SILVER_TYPES = re.compile(r"string|int|bigint|timestamp_ntz|decimal\(\d+,\d+\)")


@dataclass(frozen=True)
class ContractColumn:
    name: str
    wire_type: str
    silver_type: str
    nullable: bool


@dataclass(frozen=True)
class TableContract:
    table: str
    source_table: str
    primary_key: tuple[str, ...]
    columns: tuple[ContractColumn, ...]

    @property
    def wire_schema(self) -> StructType:
        return StructType([StructField(c.name, WIRE_TYPES[c.wire_type]) for c in self.columns])

    def typed(self, payload: str) -> list[Column]:
        """Silver columns from `payload`, a struct column parsed with `wire_schema`."""
        return [_cast(f"`{payload}`.`{c.name}`", c.silver_type).alias(c.name) for c in self.columns]

    @property
    def column_ddl(self) -> str:
        return ", ".join(f"{c.name} {c.silver_type}" for c in self.columns)


# Epoch milliseconds of 0001-01-01 and 9999-12-31 23:59:59.999; outside them timestampadd throws.
MIN_EPOCH_MS, MAX_EPOCH_MS = -62135596800000, 253402300799999


def _cast(field: str, silver_type: str) -> Column:
    if silver_type == "timestamp_ntz":
        # time.precision.mode=connect: epoch milliseconds of a naive timestamp. Adding them to the
        # NTZ epoch keeps the session time zone out of the conversion. timestampadd takes an int
        # amount, which epoch milliseconds overflow, hence whole days plus the remainder.
        epoch = "timestamp_ntz'1970-01-01 00:00:00'"
        return F.expr(
            f"case when {field} between {MIN_EPOCH_MS} and {MAX_EPOCH_MS} then "
            f"timestampadd(DAY, {field} div 86400000, "
            f"timestampadd(MILLISECOND, {field} % 86400000, {epoch})) end"
        )
    # try_cast: an out-of-range number becomes null instead of wrapping around.
    return F.expr(f"try_cast({field} as {silver_type})")


def parse_contract(table: str, doc: dict[str, Any]) -> TableContract:
    required = set(doc.get("required", []))
    columns = []
    for name, spec in doc["properties"].items():
        kinds = spec["type"] if isinstance(spec["type"], list) else [spec["type"]]
        wire = [k for k in kinds if k != "null"]
        if len(wire) != 1 or wire[0] not in WIRE_TYPES:
            raise ValueError(f"{table}.{name}: unsupported wire type {spec['type']!r}")
        if not SILVER_TYPES.fullmatch(spec["x-silver-type"]):
            raise ValueError(f"{table}.{name}: unsupported silver type {spec['x-silver-type']!r}")
        # Debezium sends every column, so nullability shows twice: "null" in type, and required.
        if ("null" in kinds) == (name in required):
            raise ValueError(f"{table}.{name}: 'required' and a null type disagree")
        columns.append(
            ContractColumn(name, wire[0], spec["x-silver-type"], nullable=name not in required)
        )

    primary_key = tuple(doc["x-primary-key"])
    by_name = {c.name: c for c in columns}
    for name in primary_key:
        if name not in by_name or by_name[name].nullable:
            raise ValueError(f"{table}: primary key column {name!r} must be a required property")
    return TableContract(table, doc["x-source-table"], primary_key, tuple(columns))


def load_contracts(directory: Path) -> dict[str, TableContract]:
    """Keyed by the bare table name, which is what bronze's `source_table` holds."""
    contracts = {
        path.stem: parse_contract(path.stem, json.loads(path.read_text()))
        for path in sorted(directory.glob("*.json"))
    }
    if not contracts:
        raise ValueError(f"no contracts in {directory}")
    return contracts
