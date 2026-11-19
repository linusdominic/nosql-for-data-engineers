"""Compare a learner's result with the reference solution's result.

Results from every console are turned into records (one dict per row, document, item or
reply element) and every value into a canonical, hashable form, so that 0.6854 from
MongoDB and Decimal('0.6854') from DuckDB, or a tz-aware and a naive UTC datetime, compare
equal. By default the comparison ignores row order and looks only at the fields the
reference returns (or a configured subset); a task that asks for an order sets
`ordered=True`.
"""

from __future__ import annotations

import math
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from nosqlde.studio.runners.base import Block, display

SIGNIFICANT_DIGITS = 10


def canonical(value: Any) -> Any:
    """A hashable value that compares equal across drivers and number types."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):  # True == 1 in Python; keep them apart
        return ("$bool", value)
    name = type(value).__name__
    if isinstance(value, (int, float, Decimal)) or name in ("Decimal128", "Int64"):
        number = float(value.to_decimal()) if name == "Decimal128" else float(value)
        if math.isnan(number):
            return "NaN"
        if number == 0:
            return 0.0
        return float(f"{number:.{SIGNIFICANT_DIGITS}g}")
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        # MongoDB keeps milliseconds; compare at that precision everywhere
        return value.replace(microsecond=value.microsecond // 1000 * 1000).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID) or name == "ObjectId":
        return str(value)
    if name == "Date" and hasattr(value, "date"):  # cassandra.util.Date
        return value.date().isoformat()
    if isinstance(value, dict):
        return tuple(sorted((str(k), canonical(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(canonical(v) for v in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((canonical(v) for v in value), key=repr))
    if hasattr(value, "iso_format"):
        return value.iso_format()
    return str(value)


def flatten(record: Any, prefix: str = "") -> dict[str, Any]:
    """Nested documents to dotted keys; arrays of documents get their index: a.0.b."""
    out: dict[str, Any] = {}
    if isinstance(record, dict):
        if not record and prefix:
            out[prefix] = {}
        for k, v in record.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict) and v:
                out.update(flatten(v, key))
            elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                for i, x in enumerate(v):
                    out.update(flatten(x, f"{key}.{i}"))
            else:
                out[key] = v
        return out
    return {prefix or "value": record}


def records(block: Block) -> list[dict[str, Any]]:
    """The rows of a block, whatever console produced it."""
    data = block.data
    if isinstance(data, dict):
        for key in ("items", "records", "rows"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
        else:
            return [flatten(data)]
    if isinstance(data, list):
        return [flatten(d) if isinstance(d, dict) else {"value": d} for d in data]
    return [{"value": data}]


@dataclass
class Comparison:
    ok: bool
    message: str
    expected: list[Any] = field(default_factory=list)
    got: list[Any] = field(default_factory=list)


def _preview(rows: Sequence[dict[str, Any]], fields: Sequence[str] | None, limit: int = 6) -> list[Any]:
    out = []
    for r in rows[:limit]:
        shown = {f: r.get(f) for f in fields} if fields else r
        out.append(display(shown))
    return out


def compare(
    expected: list[dict[str, Any]],
    got: list[dict[str, Any]],
    *,
    fields: Sequence[str] | None = None,
    ordered: bool = False,
    by_position: bool = False,
    extra_ok: bool = True,
) -> Comparison:
    """Is `got` the same result as `expected`? Never true for an empty `got`."""
    if not expected:
        raise ValueError("the reference result is empty: a check needs a non-empty expected result")
    if not got:
        return Comparison(
            False,
            "Your query returned nothing (no rows, documents or items).",
            _preview(expected, fields),
            [],
        )

    if by_position:
        width = len(expected[0])
        bad = [r for r in got if len(r) != width]
        if bad:
            return Comparison(
                False,
                f"Expected {width} column{'s' if width != 1 else ''} per row, your rows have {len(bad[0])}: "
                f"{', '.join(bad[0])}.",
                _preview(expected, None),
                _preview(got, None),
            )

        def key(r: dict[str, Any]) -> Any:
            return tuple(canonical(v) for v in r.values())

        exp_keys = [key(r) for r in expected]
        got_keys = [key(r) for r in got]
        shown: Sequence[str] | None = None
    else:
        names: list[str] = list(fields) if fields else []
        if not names:
            for r in expected:
                for k in r:
                    if k not in names:
                        names.append(k)
        have: set[str] = set()
        for r in got:
            have.update(r)
        missing = [n for n in names if n not in have]
        if missing:
            return Comparison(
                False,
                f"Your result has no field or column named {', '.join(repr(m) for m in missing)}; "
                f"it has {', '.join(sorted(have)) or 'none'}. Check the names and aliases the task asks for.",
                _preview(expected, names),
                _preview(got, None),
            )
        if not extra_ok:
            extra = sorted(have - set(names))
            if extra:
                return Comparison(
                    False,
                    f"Your result has fields the task did not ask for: {', '.join(extra)}.",
                    _preview(expected, names),
                    _preview(got, None),
                )

        def key(r: dict[str, Any]) -> Any:
            return tuple(canonical(r.get(n)) for n in names)

        exp_keys = [key(r) for r in expected]
        got_keys = [key(r) for r in got]
        shown = names

    exp_prev = _preview(expected, shown)
    got_prev = _preview(got, shown)
    if ordered:
        if exp_keys == got_keys:
            return Comparison(
                True,
                f"{len(got)} row{'s' if len(got) != 1 else ''} match, in the right order.",
                exp_prev,
                got_prev,
            )
        if Counter(exp_keys) == Counter(got_keys):
            first = next(i for i, (a, b) in enumerate(zip(exp_keys, got_keys, strict=True)) if a != b)
            return Comparison(
                False,
                f"The right rows, in the wrong order: row {first + 1} differs. The task asks for a specific order.",
                exp_prev,
                got_prev,
            )
    elif Counter(exp_keys) == Counter(got_keys):
        return Comparison(True, f"{len(got)} row{'s' if len(got) != 1 else ''} match.", exp_prev, got_prev)

    exp_count, got_count = Counter(exp_keys), Counter(got_keys)
    missing_rows = list((exp_count - got_count).elements())
    extra_rows = list((got_count - exp_count).elements())
    parts = []
    if len(expected) != len(got):
        parts.append(f"expected {len(expected)} row{'s' if len(expected) != 1 else ''}, got {len(got)}")
    if missing_rows:
        parts.append(
            f"{len(missing_rows)} expected row{'s are' if len(missing_rows) != 1 else ' is'} missing"
        )
    if extra_rows:
        parts.append(f"{len(extra_rows)} row{'s' if len(extra_rows) != 1 else ''} should not be there")
    message = "Not the same result: " + "; ".join(parts) + "."
    if missing_rows:
        idx = exp_keys.index(missing_rows[0])
        message += f" First missing: {_short(expected[idx], shown)}."
    if extra_rows:
        idx = got_keys.index(extra_rows[0])
        message += f" First unexpected: {_short(got[idx], shown)}."
    return Comparison(False, message, exp_prev, got_prev)


def _short(row: dict[str, Any], fields: Sequence[str] | None) -> str:
    shown = {f: row.get(f) for f in fields} if fields else row
    text = ", ".join(f"{k}={display(v)!r}" for k, v in shown.items())
    return text if len(text) < 220 else text[:217] + "..."
