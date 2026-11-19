"""The DuckDB console: SQL over the Parquet files in lake/, in an in-memory database.

The connection can read files under lake/ and nothing else (`allowed_directories` with
`enable_external_access = false`, then the configuration is locked), cannot install or
load extensions, and only accepts SELECT, EXPLAIN, CREATE, DROP, INSERT, UPDATE and
DELETE (on in-memory tables). COPY, ATTACH, PRAGMA, SET and the like are refused, so the
console cannot write files. Paths are relative to the repository root, as in the guide:
`FROM 'lake/capstone/marts/fct_loan.parquet'`.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import duckdb

from nosqlde.config import SETTINGS
from nosqlde.studio.runners.base import Block, RunResult, StudioError, error_block

ALLOWED_TYPES = {"SELECT", "EXPLAIN", "CREATE", "DROP", "INSERT", "UPDATE", "DELETE"}
TIMEOUT_S = 30.0


def connect(lake_dir: Path | None = None) -> duckdb.DuckDBPyConnection:
    """An in-memory connection that can only read under the lake directory."""
    lake = (lake_dir or SETTINGS.lake_dir).resolve()
    con = duckdb.connect(config={"autoinstall_known_extensions": False, "autoload_known_extensions": False})
    con.execute(f"SET allowed_directories = ['{str(lake).replace(chr(39), chr(39) * 2)}/']")
    con.execute("SET enable_external_access = false")
    con.execute("SET TimeZone = 'UTC'")  # as model.connect does: dates must not depend on the laptop
    con.execute("SET lock_configuration = true")
    return con


class DuckRunner:
    console = "duckdb"

    def __init__(self, lake_dir: Path | None = None) -> None:
        self.lake_dir = lake_dir
        self._con: duckdb.DuckDBPyConnection | None = None
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            if self._con is not None:
                self._con.close()
                self._con = None

    def run(self, text: str, max_rows: int = 200, fresh: bool = False) -> RunResult:
        """Run the statements. The console keeps one connection (views persist);
        `fresh=True` (used by checks) runs on a new, empty one."""
        result = RunResult(self.console)
        start = time.perf_counter()
        with self._lock:
            if fresh:
                con = connect(self.lake_dir)
            else:
                if self._con is None:
                    self._con = connect(self.lake_dir)
                con = self._con
            try:
                self._run(con, text, max_rows, result)
            finally:
                if fresh:
                    con.close()
        result.elapsed_ms = (time.perf_counter() - start) * 1000
        return result

    def _run(self, con: duckdb.DuckDBPyConnection, text: str, max_rows: int, result: RunResult) -> None:
        try:
            statements = con.extract_statements(text)
        except duckdb.Error as err:
            result.blocks.append(
                error_block(text.strip()[:120], StudioError(str(err), title=type(err).__name__))
            )
            return
        if not statements:
            result.blocks.append(Block(command="", kind="text", text="(nothing to run)"))
            return
        for st in statements:
            kind = str(st.type).split(".")[-1]
            sql = st.query.strip()
            if kind not in ALLOWED_TYPES:
                result.blocks.append(
                    error_block(
                        sql,
                        StudioError(
                            f"{kind} statements are not available in the studio's DuckDB console; "
                            f"it runs {', '.join(sorted(ALLOWED_TYPES))} and reads Parquet under lake/.",
                            title="Refused by the studio",
                        ),
                    )
                )
                return
            block = self._one(con, sql, max_rows)
            result.blocks.append(block)
            if block.is_error:
                return

    @staticmethod
    def _one(con: duckdb.DuckDBPyConnection, sql: str, max_rows: int) -> Block:
        timer = threading.Timer(TIMEOUT_S, con.interrupt)
        t0 = time.perf_counter()
        timer.start()
        try:
            cur = con.execute(sql)
            if cur.description is None:
                return Block(
                    command=sql, kind="text", text="OK", data=[], elapsed_ms=(time.perf_counter() - t0) * 1000
                )
            columns = [d[0] for d in cur.description]
            fetched = cur.fetchmany(max_rows + 1)
        except duckdb.Error as err:
            message = str(err)
            hint = ""
            if "Permission Error" in message:
                hint = "The DuckDB console can only read files under lake/."
            elif "No files found" in message or ("does not exist" in message and "lake/" in sql):
                hint = "Is the file there? Run the chapter's prepare step (or the capstone) first."
            block = error_block(sql, StudioError(message, title=type(err).__name__, hint=hint))
            block.elapsed_ms = (time.perf_counter() - t0) * 1000
            return block
        finally:
            timer.cancel()
        rows = [list(r) for r in fetched[:max_rows]]
        block = Block(
            command=sql,
            kind="table",
            columns=columns,
            rows=rows,
            truncated=len(fetched) > max_rows,
            data=[dict(zip(columns, r, strict=True)) for r in rows],
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )
        if sql.upper().startswith("EXPLAIN") and columns and columns[-1].endswith("plan"):
            block.kind = "text"
            block.text = "\n".join(str(r[-1]) for r in rows)
        block.notes.append(f"{len(rows)}{'+' if block.truncated else ''} row{'s' if len(rows) != 1 else ''}")
        return block
