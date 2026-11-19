from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from nosqlde import graph, lake


def test_connected_components() -> None:
    comps = graph.connected_components([("b", "a"), ("c", "b"), ("x", "y")])
    assert comps == {"a": "a", "b": "a", "c": "a", "x": "x", "y": "x"}


def test_components_from_shared_keys_needs_chains() -> None:
    pairs = [("A1", "phone:1"), ("A2", "phone:1"), ("A2", "dev:9"), ("A3", "dev:9"), ("A4", "phone:2")]
    assert graph.components_from_shared_keys(pairs) == {"A1": ["A1", "A2", "A3"], "A4": ["A4"]}


def test_write_parquet_is_atomic_and_overwrites(tmp_path: Path) -> None:
    schema = lake.arrow_schema({"id": "string", "n": "int"})
    path = tmp_path / "x" / "part.parquet"
    assert lake.write_parquet([{"id": "a", "n": 1}], path, schema) == 1
    assert lake.write_parquet([{"id": "b", "n": 2}, {"id": "c", "n": 3}], path, schema) == 2
    assert duckdb.connect().execute(f"SELECT count(*) FROM '{path}'").fetchone() == (2,)
    assert [p.name for p in path.parent.iterdir()] == ["part.parquet"]


def test_write_parquet_failure_leaves_no_partial_file(tmp_path: Path) -> None:
    schema = lake.arrow_schema({"n": "int"})
    path = tmp_path / "bad.parquet"
    with pytest.raises(Exception):  # noqa: B017 - pyarrow raises its own error types
        lake.write_parquet([{"n": "not an int"}], path, schema)
    assert list(tmp_path.iterdir()) == []


def test_state_persists(tmp_path: Path) -> None:
    s = lake.State(tmp_path / "_state" / "state.json")
    s.set("wm", "2025-01-01T00:00:00+00:00")
    assert lake.State(tmp_path / "_state" / "state.json").get("wm") == "2025-01-01T00:00:00+00:00"
    assert lake.State(tmp_path / "missing.json").get("wm", "default") == "default"


def test_arrow_schema_with_rescued_column() -> None:
    schema = lake.arrow_schema({"a": "decimal", "t": "timestamp"}, rescued=True)
    assert schema.names == ["a", "t", "_rescued"]
    assert str(schema.field("a").type) == "decimal128(12, 2)"
