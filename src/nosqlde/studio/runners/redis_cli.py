"""The Redis console: redis-cli syntax, one command per line, replies shown like redis-cli.

Lines are split with shlex (so "quoted values" and 'single quotes' work), then sent on
one connection with redis-py, so MULTI ... EXEC across lines of one run works. Replies
are read raw (RESP2, no redis-py response callbacks) and printed the way redis-cli
prints them: "strings" in quotes, (integer) n, (nil), numbered arrays.

The console uses logical database 5 (the lab uses 3, the checks 13, the capstone 7).
Commands that would change databases, block the connection, affect the whole server or
write files on it are refused; CONFIG SET is limited to the settings chapter 3 uses.
"""

from __future__ import annotations

import shlex
import threading
import time
from typing import Any

import redis

from nosqlde.config import SETTINGS
from nosqlde.studio.runners.base import Block, RunResult, ServiceDown, StudioError, error_block

STUDIO_DB = 5

REFUSED = {
    "SELECT": "the console always uses logical database 5",
    "SWAPDB": "the console always uses logical database 5",
    "MOVE": "the console always uses logical database 5",
    "FLUSHALL": "it would empty every database on the server, including the capstone's; use FLUSHDB",
    "SHUTDOWN": "it stops the server",
    "DEBUG": "it can crash or stall the server",
    "MODULE": "loading modules changes the server",
    "MONITOR": "it never returns",
    "SUBSCRIBE": "it never returns in a request/response console",
    "PSUBSCRIBE": "it never returns in a request/response console",
    "SSUBSCRIBE": "it never returns in a request/response console",
    "SYNC": "it is a replication command",
    "PSYNC": "it is a replication command",
    "REPLICAOF": "it is a replication command",
    "SLAVEOF": "it is a replication command",
    "FAILOVER": "it is a replication command",
    "MIGRATE": "it connects to other servers",
    "ACL": "it changes users and permissions",
    "SAVE": "it blocks the server; use BGSAVE",
    "CLIENT": "it can kill other connections",
    "CLUSTER": "this is a single node",
    "QUIT": "the console manages its own connection",
    "RESET": "the console manages its own connection",
    "HELLO": "the console speaks RESP2, like redis-cli",
    "AUTH": "the local container has no password",
}
#: CONFIG SET is allowed only for what chapter 3 changes
CONFIG_SET_ALLOWED = {"maxmemory", "maxmemory-policy", "appendonly", "appendfsync"}
#: blocking commands and the index of their timeout argument (seconds) from the end
BLOCKING_LAST_ARG_TIMEOUT = {"BLPOP", "BRPOP", "BZPOPMIN", "BZPOPMAX", "BRPOPLPUSH", "BLMOVE"}
MAX_BLOCK_SECONDS = 5
#: commands whose string replies are status replies (printed without quotes)
STATUS_COMMANDS = {"TYPE", "BGSAVE", "BGREWRITEAOF", "PING", "LASTSAVE"}
STATUS_VALUES = {"OK", "PONG", "QUEUED"}


def split_line(line: str) -> list[str]:
    """Split one redis-cli line into arguments (raises ValueError on a bad quote)."""
    lexer = shlex.shlex(line, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def commands(text: str) -> list[tuple[int, str, list[str]]]:
    """(line number, line, args) for every non-empty, non-comment line."""
    out = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        try:
            args = split_line(line)
        except ValueError as err:
            raise StudioError(
                f"line {number}: {err} (check the quotes)\n  {line}", title="Cannot read the command"
            ) from None
        if args:
            out.append((number, line, args))
    return out


def refusal(args: list[str]) -> str | None:
    """Why the console refuses this command, or None."""
    name = args[0].upper()
    if name in REFUSED:
        return f"{name} is not available in the studio: {REFUSED[name]}."
    if name == "CONFIG" and len(args) >= 2:
        sub = args[1].upper()
        if sub == "SET":
            params = {args[i].lower() for i in range(2, len(args), 2)}
            bad = params - CONFIG_SET_ALLOWED
            if bad:
                return (
                    f"CONFIG SET {', '.join(sorted(bad))} is not available in the studio; "
                    f"only {', '.join(sorted(CONFIG_SET_ALLOWED))} can be changed here."
                )
        elif sub in ("REWRITE", "RESETSTAT"):
            return f"CONFIG {sub} is not available in the studio."
    if name in BLOCKING_LAST_ARG_TIMEOUT and len(args) >= 2:
        try:
            seconds = float(args[-1])
        except ValueError:
            return None
        if seconds == 0 or seconds > MAX_BLOCK_SECONDS:
            return f"{name} with a timeout of {args[-1]}s would hold the console; use 1 to {MAX_BLOCK_SECONDS} seconds."
    if name in ("XREAD", "XREADGROUP"):
        upper = [a.upper() for a in args]
        if "BLOCK" in upper:
            i = upper.index("BLOCK")
            try:
                ms = int(args[i + 1])
            except (IndexError, ValueError):
                return None
            if ms == 0 or ms > MAX_BLOCK_SECONDS * 1000:
                return f"{name} BLOCK {ms} would hold the console; use 1 to {MAX_BLOCK_SECONDS * 1000} ms."
    if name in ("EVAL", "EVALSHA", "EVAL_RO", "EVALSHA_RO", "FCALL", "FUNCTION", "SCRIPT"):
        return f"{name} is not available in the studio: scripts are out of scope for chapter 3."
    return None


def quote(value: str) -> str:
    """redis-cli's quoting of a bulk string."""
    out = ['"']
    for ch in value:
        if ch in ('"', "\\"):
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 32 or ord(ch) == 127:
            out.append(f"\\x{ord(ch):02x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def format_reply(reply: Any, command: str = "", indent: int = 0) -> str:
    """Format a raw RESP2 reply the way redis-cli does."""
    if isinstance(reply, redis.ResponseError):
        return f"(error) {reply}"
    if reply is None:
        return "(nil)"
    if isinstance(reply, bool):
        return f"(integer) {int(reply)}"
    if isinstance(reply, int):
        return f"(integer) {reply}"
    if isinstance(reply, bytes):
        reply = reply.decode("utf-8", "backslashreplace")
    if isinstance(reply, str):
        if command in STATUS_COMMANDS or reply in STATUS_VALUES:
            return reply
        return quote(reply)
    if isinstance(reply, (list, tuple)):
        if not reply:
            return "(empty array)"
        width = len(str(len(reply)))
        lines = []
        for i, item in enumerate(reply, start=1):
            label = f"{str(i).rjust(width)}) "
            inner = format_reply(item, "", indent + len(label))
            pad = "" if i == 1 else " " * indent
            lines.append(pad + label + inner)
        return "\n".join(lines)
    return str(reply)


def plain(reply: Any) -> Any:
    """A JSON-safe version of a reply for checks (errors become {'error': ...})."""
    if isinstance(reply, redis.ResponseError):
        return {"error": str(reply)}
    if isinstance(reply, (list, tuple)):
        return [plain(r) for r in reply]
    if isinstance(reply, bytes):
        return reply.decode("utf-8", "backslashreplace")
    return reply


class RedisRunner:
    console = "redis"

    def __init__(self, db: int = STUDIO_DB, url: str | None = None) -> None:
        self.db = db
        self.url = url or SETTINGS.redis_url
        self._client: redis.Redis | None = None
        self._lock = threading.Lock()

    def client(self) -> redis.Redis:
        with self._lock:
            if self._client is None:
                self._client = redis.Redis.from_url(
                    self.url,
                    db=self.db,
                    decode_responses=True,
                    encoding_errors="backslashreplace",
                    protocol=2,
                    socket_timeout=MAX_BLOCK_SECONDS + 5,
                    socket_connect_timeout=2,
                )
            return self._client

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None

    def run(self, text: str, max_rows: int = 200) -> RunResult:
        result = RunResult(self.console)
        start = time.perf_counter()
        try:
            parsed = commands(text)
        except StudioError as err:
            result.blocks.append(error_block(text.strip()[:120], err))
            return result
        if not parsed:
            result.blocks.append(Block(command="", kind="text", text="(nothing to run)"))
            return result
        for _, line, args in parsed:
            why = refusal(args)
            if why:
                result.blocks.append(error_block(line, StudioError(why, title="Refused by the studio")))
                result.elapsed_ms = (time.perf_counter() - start) * 1000
                return result
        pool = self.client().connection_pool
        try:
            conn: Any = pool.get_connection()
        except (redis.ConnectionError, redis.TimeoutError, OSError) as err:
            result.blocks.append(error_block(text.strip().splitlines()[0], self._down(err)))
            return result
        in_multi = False
        try:
            for _, line, args in parsed:
                name = args[0].upper()
                t0 = time.perf_counter()
                try:
                    conn.send_command(*args)
                    reply: Any = conn.read_response()
                except redis.ResponseError as err:
                    reply = err
                except (redis.ConnectionError, redis.TimeoutError, OSError) as err:
                    conn.disconnect()
                    result.blocks.append(error_block(line, self._down(err)))
                    break
                elapsed = (time.perf_counter() - t0) * 1000
                if name == "MULTI" and not isinstance(reply, redis.ResponseError):
                    in_multi = True
                elif name in ("EXEC", "DISCARD"):
                    in_multi = False
                block = Block(
                    command=line,
                    kind="error" if isinstance(reply, redis.ResponseError) else "text",
                    text=format_reply(reply, name),
                    elapsed_ms=elapsed,
                    data=plain(reply),
                )
                if block.kind == "error":
                    block.error_title = "Redis replied with an error"
                result.blocks.append(block)
        finally:
            if in_multi:  # never leave a transaction open on a pooled connection
                try:
                    conn.send_command("DISCARD")
                    conn.read_response()
                except Exception:
                    conn.disconnect()
            pool.release(conn)
        result.elapsed_ms = (time.perf_counter() - start) * 1000
        return result

    def _down(self, err: BaseException) -> ServiceDown:
        return ServiceDown(
            f"Redis is not reachable at {self.url} ({type(err).__name__}: {err}).",
            title="Redis is down",
            hint="Start it with `make up-03` (or `make up-capstone`).",
        )
