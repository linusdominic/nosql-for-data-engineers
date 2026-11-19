"""Console helpers that need no database: redis-cli parsing and output, CQL splitting and
cqlsh commands, DynamoDB JSON mode parsing, and the DuckDB sandbox (DuckDB is embedded)."""

from __future__ import annotations

from pathlib import Path

import pytest
import redis

from nosqlde.studio.runners.base import Block, StudioError, display
from nosqlde.studio.runners.cql import CqlState, shell_command, split_statements
from nosqlde.studio.runners.duck import DuckRunner
from nosqlde.studio.runners.dynamo import parse_json_requests
from nosqlde.studio.runners.redis_cli import commands, format_reply, plain, quote, refusal

# ---------------------------------------------------------------- redis


def test_redis_lines_are_split_like_a_shell() -> None:
    parsed = commands('# a comment\nSET k "two words"\n\n  SINTER "ch03:phone:+999 7000:applications" b  \n')
    assert [(n, a) for n, _, a in parsed] == [
        (2, ["SET", "k", "two words"]),
        (4, ["SINTER", "ch03:phone:+999 7000:applications", "b"]),
    ]


def test_redis_bad_quote_is_a_clear_error() -> None:
    with pytest.raises(StudioError, match="line 1"):
        commands('SET k "open')


@pytest.mark.parametrize(
    ("line", "needle"),
    [
        ("FLUSHALL", "FLUSHDB"),
        ("select 3", "logical database 5"),
        ("SHUTDOWN NOSAVE", "stops the server"),
        ("CONFIG SET dir /tmp", "only"),
        ("CONFIG SET dbfilename x.rdb", "only"),
        ("CONFIG REWRITE", "not available"),
        ("BLPOP q 0", "hold the console"),
        ("BRPOP q 60", "hold the console"),
        ("XREAD BLOCK 0 STREAMS s $", "hold the console"),
        ("MONITOR", "never returns"),
        ("EVAL 'return 1' 0", "scripts"),
        ("DEBUG SLEEP 10", "stall"),
        ("MODULE LOAD /x.so", "modules"),
    ],
)
def test_redis_refuses_dangerous_or_blocking_commands(line: str, needle: str) -> None:
    why = refusal(line.split())
    assert why is not None and needle in why


@pytest.mark.parametrize(
    "line",
    [
        "CONFIG SET maxmemory-policy volatile-lru",
        "CONFIG GET *",
        "BLPOP q 2",
        "XREADGROUP GROUP g c BLOCK 100 STREAMS s >",
        "FLUSHDB",
        "GET k",
    ],
)
def test_redis_allows_what_chapter_3_uses(line: str) -> None:
    assert refusal(line.split()) is None


def test_redis_replies_print_like_redis_cli() -> None:
    assert format_reply(None) == "(nil)"
    assert format_reply(42) == "(integer) 42"
    assert format_reply("OK") == "OK"
    assert format_reply("string", "TYPE") == "string"
    assert format_reply("funded") == '"funded"'
    assert format_reply([]) == "(empty array)"
    assert format_reply(["a", "1"]) == '1) "a"\n2) "1"'
    nested = format_reply([["1-0", ["event_id", "e1"]]])
    assert nested == '1) 1) "1-0"\n   2) 1) "event_id"\n      2) "e1"'
    assert format_reply(redis.ResponseError("WRONGTYPE x")) == "(error) WRONGTYPE x"
    assert quote('a"b\n') == '"a\\"b\\n"'
    assert plain([1, redis.ResponseError("bad")]) == [1, {"error": "bad"}]


# ---------------------------------------------------------------- cql


def test_cql_statements_split_outside_quotes_and_comments() -> None:
    text = "TRACING ON; -- trace it\nSELECT 'a;b' FROM t; /* c; */ SELECT \"x;\" FROM t2 // end;\n;"
    assert split_statements(text) == ["TRACING ON", "SELECT 'a;b' FROM t", 'SELECT "x;" FROM t2']
    assert split_statements("SELECT 'it''s; fine' FROM t") == ["SELECT 'it''s; fine' FROM t"]


def test_cypher_keeps_dash_dash_and_backticks() -> None:
    text = "MATCH (a)--(b) RETURN `a;b`; // comment\nRETURN 1"
    assert split_statements(text, line_comments=("//",), quotes="'\"`") == [
        "MATCH (a)--(b) RETURN `a;b`",
        "RETURN 1",
    ]


def test_cqlsh_tracing_and_consistency() -> None:
    st = CqlState()
    assert st.consistency == "LOCAL_ONE" and not st.tracing
    block = shell_command("tracing on", st)
    assert isinstance(block, Block) and st.tracing
    shell_command("CONSISTENCY quorum", st)
    assert st.consistency == "QUORUM"
    assert shell_command("SELECT * FROM t", st) is None
    with pytest.raises(StudioError):
        shell_command("CONSISTENCY SOMETIMES", st)
    with pytest.raises(StudioError, match="cqlsh command"):
        shell_command("COPY t TO 'x.csv'", st)


# ---------------------------------------------------------------- dynamodb


def test_dynamodb_json_mode_requests() -> None:
    reqs = parse_json_requests('[{"op": "Query", "TableName": "t"}, {"op": "GetItem"}]')
    assert [r["op"] for r in reqs] == ["Query", "GetItem"]
    with pytest.raises(StudioError, match="line 1"):
        parse_json_requests('{"op": "Query",}')
    with pytest.raises(StudioError, match='needs an "op"'):
        parse_json_requests('{"TableName": "t"}')
    with pytest.raises(StudioError, match="not available"):
        parse_json_requests('{"op": "DeleteTable", "TableName": "t"}')


# ---------------------------------------------------------------- duckdb sandbox


@pytest.fixture
def lake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "lake").mkdir()
    (tmp_path / "outside.csv").write_text("a\n1\n")
    import duckdb

    duckdb.connect().execute("COPY (SELECT 1 AS a UNION ALL SELECT 2) TO 'lake/t.parquet' (FORMAT parquet)")
    return tmp_path / "lake"


def test_duckdb_reads_the_lake(lake: Path) -> None:
    r = DuckRunner(lake).run("SELECT sum(a) AS s FROM 'lake/t.parquet'")
    assert r.error is None and r.blocks[0].data == [{"s": 3}]


@pytest.mark.parametrize(
    ("sql", "needle"),
    [
        ("SELECT * FROM read_csv('outside.csv')", "Permission"),
        ("COPY (SELECT 1) TO 'lake/x.csv'", "COPY statements are not available"),
        ("ATTACH 'lake/x.duckdb'", "ATTACH statements are not available"),
        ("SET enable_external_access = true", "SET statements are not available"),
        ("INSTALL httpfs", "not available"),
        ("PRAGMA version", "PRAGMA statements are not available"),
    ],
)
def test_duckdb_cannot_leave_the_lake_or_write_files(lake: Path, sql: str, needle: str) -> None:
    r = DuckRunner(lake).run(sql)
    assert r.error is not None and needle in r.error.text, r.error.text
    assert not (lake / "x.csv").exists()


def test_duckdb_console_keeps_views_but_checks_start_fresh(lake: Path) -> None:
    runner = DuckRunner(lake)
    assert runner.run("CREATE VIEW v AS SELECT 7 AS n").error is None
    assert runner.run("SELECT n FROM v").blocks[0].data == [{"n": 7}]
    assert runner.run("SELECT n FROM v", fresh=True).error is not None
    runner.close()


def test_display_tags_typed_values() -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    assert display(datetime(2025, 1, 1, tzinfo=UTC)) == {"$date": "2025-01-01T00:00:00.000Z"}
    assert display(Decimal("1.50")) == {"$numberDecimal": "1.50"}
    assert display(2**60) == {"$numberLong": str(2**60)}
    assert display({"a": [1, None]}) == {"a": [1, None]}
