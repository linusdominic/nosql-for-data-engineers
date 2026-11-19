"""Plain-text output helpers shared by the labs, checks and capstone."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def heading(text: str) -> None:
    print(f"\n{'=' * 78}\n{text}\n{'=' * 78}")


def step(number: str, title: str) -> None:
    print(f"\n--- Step {number}: {title} ---")


def say(text: str = "") -> None:
    print(text)


def _default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def as_json(value: Any, indent: int | None = 2) -> str:
    return json.dumps(value, default=_default, indent=indent)


def show_json(value: Any) -> None:
    print(as_json(value))


def fmt(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, float):
        return f"{value:,.4f}".rstrip("0").rstrip(".") if not value.is_integer() else f"{value:,.0f}"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}" if abs(value) >= 10_000 else str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def table(rows: Sequence[Sequence[Any]], headers: Sequence[str]) -> None:
    """Print an aligned text table."""
    cells = [[fmt(v) for v in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in cells:
        widths = [max(w, len(c)) for w, c in zip(widths, row, strict=True)]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True))
    print(line)
    print("  ".join("-" * w for w in widths))
    for row in cells:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)))
