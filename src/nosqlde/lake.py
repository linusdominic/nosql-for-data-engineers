"""A tiny Parquet "lake" on local disk, with the habits that make pipelines re-runnable.

Three habits, each a function here:

* `write_parquet` writes to a temporary file and renames it into place, so a crash
  never leaves half a file that a reader could pick up.
* Output paths are derived from the data's own boundaries (a day, or a watermark
  window), never from the wall clock. Running the same extract twice writes the same
  file twice, so it overwrites instead of duplicating.
* `State` keeps watermarks in a JSON file next to the data, written atomically, and
  only after the data it describes has been written.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from nosqlde.drift import RESCUED

ARROW_TYPES: dict[str, Any] = {
    "string": pa.string(),
    "int": pa.int64(),
    "float": pa.float64(),
    "decimal": pa.decimal128(12, 2),
    "bool": pa.bool_(),
    "timestamp": pa.timestamp("us", tz="UTC"),
    "date": pa.date32(),
}


def arrow_schema(schema: dict[str, str], rescued: bool = False) -> Any:
    """A pyarrow schema from the drift-module type names."""
    fields = [pa.field(col, ARROW_TYPES[t]) for col, t in schema.items()]
    if rescued:
        fields.append(pa.field(RESCUED, pa.string()))
    return pa.schema(fields)


def write_parquet(rows: list[dict[str, Any]], path: Path, schema: Any) -> int:
    """Write rows to `path` atomically. Returns the number of rows written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows, schema=schema)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".parquet")
    os.close(fd)
    try:
        pq.write_table(table, tmp)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return int(table.num_rows)


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def write_json(path: Path, payload: Any) -> None:
    """Atomic JSON write (temporary file, then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".tmp-{path.name}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n")
    os.replace(tmp, path)


class State:
    """Watermarks and other pipeline state, persisted as one JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set and persist immediately."""
        self.data[key] = value
        write_json(self.path, self.data)


def parquet_glob(root: Path, *parts: str) -> str:
    """A glob DuckDB can read, e.g. lake/raw/mongo/applications/**/*.parquet."""
    return str(root.joinpath(*parts, "**", "*.parquet"))


def dir_size(path: Path) -> int:
    """Total bytes of files under `path`."""
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
