"""What every console returns: a list of blocks, one per statement, each with timing.

A block is shown in the browser (as a table, a JSON tree, plain text, a query plan or an
error) and also keeps the raw result in `data`, which the checks compare. `data` never
leaves the server; `to_json()` sends only what the browser needs.
"""

from __future__ import annotations

import base64
import math
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from decimal import Decimal
from typing import Any, Literal

Kind = Literal["table", "json", "text", "plan", "error"]

#: rows the browser is sent per block; checks ask for more
DISPLAY_ROWS = 200
#: rows a check reads per block
CHECK_ROWS = 20_000


class StudioError(Exception):
    """An error the learner should see as one clear message (not a stack trace)."""

    def __init__(self, message: str, *, title: str = "Error", hint: str = "") -> None:
        super().__init__(message)
        self.title = title
        self.hint = hint


class ServiceDown(StudioError):
    """The database behind a console is not reachable."""


@dataclass
class Block:
    """The result of one statement."""

    command: str
    kind: Kind = "text"
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    value: Any = None
    text: str = ""
    notes: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    truncated: bool = False
    error_title: str = ""
    hint: str = ""
    #: the raw result, for checks (not sent to the browser)
    data: Any = None

    @property
    def is_error(self) -> bool:
        return self.kind == "error"

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "command": self.command,
            "kind": self.kind,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "notes": self.notes,
        }
        if self.kind in ("table", "plan"):
            out["columns"] = self.columns
            out["rows"] = [[display(v) for v in row] for row in self.rows[:DISPLAY_ROWS]]
            out["row_count"] = len(self.rows)
            out["truncated"] = self.truncated or len(self.rows) > DISPLAY_ROWS
        if self.kind in ("json", "plan", "table") and self.value is not None:
            out["value"] = display(self.value)
        if self.kind in ("text", "error"):
            out["text"] = self.text
        if self.kind == "error":
            out["title"] = self.error_title or "Error"
            out["hint"] = self.hint
        return out


def error_block(command: str, err: BaseException, *, title: str = "", hint: str = "") -> Block:
    if isinstance(err, StudioError):
        title = title or err.title
        hint = hint or err.hint
    return Block(
        command=command,
        kind="error",
        text=str(err) or type(err).__name__,
        error_title=title or type(err).__name__,
        hint=hint,
    )


@dataclass
class RunResult:
    console: str
    blocks: list[Block] = field(default_factory=list)
    elapsed_ms: float = 0.0

    @property
    def error(self) -> Block | None:
        return next((b for b in self.blocks if b.is_error), None)

    @property
    def last(self) -> Block | None:
        return self.blocks[-1] if self.blocks else None

    def to_json(self) -> dict[str, Any]:
        return {
            "console": self.console,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "blocks": [b.to_json() for b in self.blocks],
        }


@contextmanager
def timed(block: Block) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        block.elapsed_ms = (time.perf_counter() - start) * 1000


def display(value: Any) -> Any:
    """A JSON-safe copy for the browser. Typed values become one-key objects the
    frontend renders the way the database's own shell would ({"$date": ...})."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        # JavaScript loses precision above 2**53: send big integers as text
        return value if abs(value) < 2**53 else {"$numberLong": str(value)}
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return {"$number": str(value)}
        return value
    if isinstance(value, Decimal):
        return {"$numberDecimal": str(value)}
    if isinstance(value, datetime):
        return {"$date": iso(value)}
    if isinstance(value, date):
        return {"$dateOnly": value.isoformat()}
    if isinstance(value, dtime):
        return {"$time": value.isoformat()}
    if isinstance(value, timedelta):
        return {"$duration": str(value)}
    if isinstance(value, uuid.UUID):
        return {"$uuid": str(value)}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"$binary": base64.b64encode(bytes(value)).decode()}
    if isinstance(value, dict):
        return {str(k): display(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = sorted(value, key=repr) if isinstance(value, (set, frozenset)) else value
        return [display(v) for v in items]
    tagged = _tagged(value)
    if tagged is not None:
        return tagged
    return str(value)


def _tagged(value: Any) -> Any:
    """BSON and driver types, without importing every driver here."""
    name = type(value).__name__
    if name == "ObjectId":
        return {"$oid": str(value)}
    if name == "Decimal128":
        return {"$numberDecimal": str(value)}
    if name == "Regex":
        flags = value.flags
        if isinstance(flags, int):  # bson keeps re flags as an int
            flags = "".join(
                c for c, bit in (("i", 2), ("m", 8), ("s", 16), ("u", 32), ("x", 64)) if flags & bit
            )
        return {"$regex": value.pattern, "$options": flags}
    if name == "Pattern":
        return {"$regex": value.pattern, "$options": ""}
    if name in ("Int64",):
        return display(int(value))
    if name == "Timestamp" and hasattr(value, "time"):
        return {"$timestamp": {"t": value.time, "i": value.inc}}
    if name == "Date" and hasattr(value, "date"):  # cassandra.util.Date
        try:
            return {"$dateOnly": value.date().isoformat()}
        except Exception:
            return {"$dateOnly": str(value)}
    if name in ("DateTime", "Date", "Time", "Duration") and hasattr(value, "iso_format"):  # neo4j.time
        return {"$date" if name == "DateTime" else "$" + name.lower(): value.iso_format()}
    if name in ("SortedSet", "OrderedMapSerializedKey", "OrderedMap"):
        return display(list(value) if name == "SortedSet" else dict(value))
    return None


def iso(value: datetime) -> str:
    """ISO 8601 in UTC with milliseconds and a Z, like mongosh and cqlsh print instants."""
    if value.tzinfo is not None:  # naive values from the drivers are already UTC
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.isoformat(timespec="milliseconds") + "Z"
