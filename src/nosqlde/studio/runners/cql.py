"""The Cassandra console: CQL through cassandra-driver, with a few cqlsh commands.

* Statements are separated by `;` (quotes and comments are respected).
* `TRACING ON` / `TRACING OFF` and `CONSISTENCY <level>` work like in cqlsh. They are
  remembered for the console (like a cqlsh session); a check starts from the defaults.
* Every statement runs in the chapter's keyspace (`USE` changes it for the console).
* With tracing on, each statement's server trace is shown under the result, with the
  "Read N live rows and M tombstone cells" lines pulled out.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from nosqlde.config import SETTINGS
from nosqlde.studio.runners.base import Block, RunResult, ServiceDown, StudioError, error_block

STUDIO_KEYSPACE = "larkspur_studio"
LEVELS = (
    "ANY",
    "ONE",
    "TWO",
    "THREE",
    "QUORUM",
    "ALL",
    "LOCAL_QUORUM",
    "EACH_QUORUM",
    "SERIAL",
    "LOCAL_SERIAL",
    "LOCAL_ONE",
)
DEFAULT_LEVEL = "LOCAL_ONE"  # the Python driver's default, as chapter 4 says
TIMEOUT_S = 20
#: rows per page; the console still shows only the first rows
FETCH_SIZE = 5000
_TRACE_SUMMARY = re.compile(r"Read \d+ live rows and \d+ tombstone cells|Submitting range requests")


@dataclass
class CqlState:
    """What cqlsh would remember between commands."""

    keyspace: str = STUDIO_KEYSPACE
    consistency: str = DEFAULT_LEVEL
    tracing: bool = False


def split_statements(
    text: str, line_comments: tuple[str, ...] = ("--", "//"), quotes: str = "'\""
) -> list[str]:
    """Split on `;` outside quotes and comments; drop comment-only pieces.

    CQL has `--` and `//` line comments; Cypher only `//` (`--` is an undirected
    relationship there) and also quotes names with backticks.
    """
    out: list[str] = []
    buf: list[str] = []
    i, n = 0, len(text)
    quote: str | None = None
    while i < n:
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                if i + 1 < n and text[i + 1] == quote:  # '' inside a string
                    buf.append(text[i + 1])
                    i += 1
                else:
                    quote = None
            i += 1
            continue
        if ch in quotes:
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if text.startswith("$$", i):
            end = text.find("$$", i + 2)
            end = n if end < 0 else end + 2
            buf.append(text[i:end])
            i = end
            continue
        if any(text.startswith(c, i) for c in line_comments):
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        if ch == ";":
            out.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    out.append("".join(buf).strip())
    return [s for s in out if s]


_SHELL = re.compile(r"^(TRACING|CONSISTENCY|SERIAL\s+CONSISTENCY)\b(.*)$", re.IGNORECASE | re.DOTALL)
_SHELL_ONLY = re.compile(
    r"^(SOURCE|COPY|CAPTURE|LOGIN|EXIT|QUIT|PAGING|EXPAND|SHOW|CLEAR|CLS|HELP)\b", re.IGNORECASE
)


def shell_command(stmt: str, state: CqlState) -> Block | None:
    """Handle a cqlsh command (TRACING, CONSISTENCY). None if it is plain CQL."""
    m = _SHELL.match(stmt.strip())
    if not m:
        if _SHELL_ONLY.match(stmt.strip()):
            word = stmt.split()[0].upper()
            raise StudioError(
                f"{word} is a cqlsh command that the studio does not support; "
                "TRACING ON/OFF and CONSISTENCY <level> are supported.",
                title="Not supported here",
            )
        return None
    word = re.sub(r"\s+", " ", m.group(1).upper())
    arg = m.group(2).strip().upper()
    if word == "TRACING":
        if arg not in ("ON", "OFF"):
            if not arg:
                return Block(
                    command=stmt,
                    kind="text",
                    text=f"Tracing is currently {'enabled' if state.tracing else 'disabled'}.",
                )
            raise StudioError("use TRACING ON or TRACING OFF", title="Bad TRACING command")
        state.tracing = arg == "ON"
        text = "Now Tracing is enabled" if state.tracing else "Disabled Tracing."
        return Block(command=stmt, kind="text", text=text, data={"tracing": state.tracing})
    if word == "CONSISTENCY":
        if not arg:
            return Block(command=stmt, kind="text", text=f"Current consistency level is {state.consistency}.")
        if arg not in LEVELS:
            raise StudioError(
                f"unknown consistency level {arg}; use one of {', '.join(LEVELS)}",
                title="Bad CONSISTENCY command",
            )
        state.consistency = arg
        return Block(
            command=stmt, kind="text", text=f"Consistency level set to {arg}.", data={"consistency": arg}
        )
    raise StudioError("SERIAL CONSISTENCY is not supported in the studio", title="Not supported here")


def _value(v: Any) -> Any:
    return v


def server_message(err: BaseException) -> tuple[str, str]:
    """(title, message) for a driver error, without the driver's wrapping."""
    name = type(err).__name__
    text = str(err)
    m = re.search(r'message="(.*)"', text, re.DOTALL)
    if m:
        text = m.group(1)
    if name == "Unavailable" or "Cannot achieve consistency level" in text:
        need = re.search(r"required_replicas\W+(\d+)", str(err))
        alive = re.search(r"alive_replicas\W+(\d+)", str(err))
        level = re.search(r"consistency level (\w+)", str(err))
        parts = [f"Cannot achieve consistency level {level.group(1) if level else '?'}"]
        if need and alive:
            parts.append(f"needs {need.group(1)} replicas, {alive.group(1)} alive")
        return "Unavailable", ": ".join(parts)
    if name == "NoHostAvailable":
        return "Cassandra is down", text
    return name, text


class CqlRunner:
    console = "cql"

    def __init__(self, keyspace: str = STUDIO_KEYSPACE) -> None:
        self.default_keyspace = keyspace
        self.state = CqlState(keyspace=keyspace)
        self._session: Any = None
        self._lock = threading.Lock()

    def session(self) -> Any:
        with self._lock:
            if self._session is None:
                import logging

                from cassandra.cluster import EXEC_PROFILE_DEFAULT, Cluster, ExecutionProfile
                from cassandra.policies import RoundRobinPolicy

                logging.getLogger("cassandra").setLevel(logging.ERROR)
                cluster = Cluster(
                    [SETTINGS.cassandra_host],
                    port=SETTINGS.cassandra_port,
                    execution_profiles={
                        EXEC_PROFILE_DEFAULT: ExecutionProfile(
                            load_balancing_policy=RoundRobinPolicy(), request_timeout=TIMEOUT_S
                        )
                    },
                    connect_timeout=5,
                    control_connection_timeout=5,
                )
                try:
                    session = cluster.connect()
                    # Let the server timestamp every write. With client timestamps, a plain
                    # write from the laptop and an LWT (timestamped by the server's Paxos
                    # round) are ordered by two different clocks, and the Docker VM's clock
                    # is not the host's: chapter 4's "mixing LWT and plain writes" trap.
                    session.use_client_timestamp = False
                    self._session = session
                except Exception as err:
                    cluster.shutdown()
                    raise ServiceDown(
                        f"Cassandra is not reachable at {SETTINGS.cassandra_host}:{SETTINGS.cassandra_port} "
                        f"({type(err).__name__}).",
                        title="Cassandra is down",
                        hint="Start it with `make up-04` (or `make up-capstone`); it needs about a minute.",
                    ) from err
            return self._session

    def close(self) -> None:
        with self._lock:
            if self._session is not None:
                self._session.cluster.shutdown()
                self._session = None

    def run(self, text: str, max_rows: int = 200, state: CqlState | None = None) -> RunResult:
        """Run every statement. `state` defaults to the console's own (cqlsh-like) state."""
        st = state if state is not None else self.state
        result = RunResult(self.console)
        start = time.perf_counter()
        statements = split_statements(text)
        if not statements:
            result.blocks.append(Block(command="", kind="text", text="(nothing to run)"))
            return result
        for stmt in statements:
            t0 = time.perf_counter()
            try:
                block = shell_command(stmt, st)
                if block is None:
                    block = self._execute(stmt, st, max_rows)
            except ServiceDown as err:
                block = error_block(stmt, err)
            except StudioError as err:
                block = error_block(stmt, err)
            except Exception as err:
                title, message = server_message(err)
                hint = ""
                if title == "Cassandra is down":
                    hint = "Start it with `make up-04` (or `make up-capstone`)."
                block = error_block(stmt, StudioError(message, title=title, hint=hint))
                block.data = {"error": title, "message": message}
            if not block.elapsed_ms:
                block.elapsed_ms = (time.perf_counter() - t0) * 1000
            result.blocks.append(block)
            if block.is_error:
                break
        result.elapsed_ms = (time.perf_counter() - start) * 1000
        return result

    def _execute(self, stmt: str, st: CqlState, max_rows: int) -> Block:
        from cassandra import ConsistencyLevel
        from cassandra.query import SimpleStatement

        session = self.session()
        use = re.match(r"^\s*USE\s+(\"?)(\w+)\1\s*$", stmt, re.IGNORECASE)
        if use:
            session.execute(stmt)
            st.keyspace = use.group(2) if use.group(1) else use.group(2).lower()
            return Block(
                command=stmt,
                kind="text",
                text=f"Now using keyspace {st.keyspace}.",
                data={"keyspace": st.keyspace},
            )
        missing_keyspace = False
        if st.keyspace and session.keyspace != st.keyspace:
            try:
                session.set_keyspace(st.keyspace)
            except Exception:
                missing_keyspace = True
        level = getattr(ConsistencyLevel, st.consistency)
        statement = SimpleStatement(stmt, consistency_level=level, fetch_size=FETCH_SIZE)
        t0 = time.perf_counter()
        try:
            rs = session.execute(statement, trace=st.tracing, timeout=TIMEOUT_S)
        except Exception as err:
            if missing_keyspace:
                raise StudioError(
                    f"{server_message(err)[1]}\nThe keyspace {st.keyspace} does not exist yet.",
                    title="Keyspace not prepared",
                    hint="Click Prepare in the chapter 4 lesson to create and load it.",
                ) from err
            raise
        columns = list(rs.column_names or [])
        rows: list[list[Any]] = []
        truncated = False
        for row in rs:
            if len(rows) >= max_rows:
                truncated = True
                break
            rows.append([_value(v) for v in row])
        elapsed = (time.perf_counter() - t0) * 1000
        is_select = bool(re.match(r"^\s*(SELECT|DESCRIBE|DESC|LIST)\b", stmt, re.IGNORECASE))
        if columns or is_select:
            block = Block(
                command=stmt,
                kind="table",
                columns=columns,
                rows=rows,
                truncated=truncated,
                data=[dict(zip(columns, r, strict=True)) for r in rows],
            )
            block.notes.append(f"({len(rows)}{'+' if truncated else ''} rows)")
        else:
            block = Block(command=stmt, kind="text", text="OK", data=[])
        block.elapsed_ms = elapsed
        block.notes.append(f"consistency {st.consistency}")
        warnings = getattr(rs.response_future, "warnings", None) or []
        for w in warnings:
            block.notes.append(f"server warning: {w}")
        if st.tracing:
            self._add_trace(block, rs)
        return block

    @staticmethod
    def _add_trace(block: Block, rs: Any) -> None:
        try:
            trace = rs.get_query_trace(max_wait_sec=3)
        except Exception as err:  # the trace is written asynchronously
            block.notes.append(f"trace not available yet ({type(err).__name__})")
            return
        events = [
            [
                e.description,
                e.source,
                e.source_elapsed.microseconds + e.source_elapsed.seconds * 1_000_000
                if e.source_elapsed
                else None,
            ]
            for e in trace.events
        ]
        reads = [e[0] for e in events if _TRACE_SUMMARY.search(e[0])]
        summary = {
            "session_id": str(trace.trace_id),
            "duration_us": trace.duration.microseconds + trace.duration.seconds * 1_000_000
            if trace.duration
            else None,
            "coordinator": str(trace.coordinator),
            "summary": reads,
        }
        block.value = {
            "trace": summary,
            "events": [{"activity": a, "source": str(s), "source_elapsed_us": us} for a, s, us in events],
        }
        for line in reads:
            block.notes.append(f"trace: {line}")
        if isinstance(block.data, list):
            block.data = {"rows": block.data, "trace": reads}
        else:
            block.data = {"rows": [], "trace": reads}
