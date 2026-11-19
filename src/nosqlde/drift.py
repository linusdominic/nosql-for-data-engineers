"""Make flattened rows fit a fixed table schema, and report every deviation.

A document collection has no enforced schema, so over time it drifts: a field goes
missing, a number arrives as a string, a new field appears. A Parquet file and a
warehouse table do have a schema. This module sits between the two:

* missing field   -> NULL, counted under `missing`
* wrong type      -> converted if it can be done without guessing, counted under
                     `coerced`; otherwise NULL, counted under `failed`
* unknown field   -> kept as JSON in a `_rescued` column (or dropped, or an error),
                     counted under `unexpected`

The report is the point. A pipeline that silently "handles" drift hides problems; one
that counts them lets you alert when `failed` is not zero.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

TYPES = ("string", "int", "float", "decimal", "bool", "timestamp", "date")
RESCUED = "_rescued"
OnNew = Literal["rescue", "drop", "fail"]


class SchemaDriftError(ValueError):
    """Raised in strict mode when a row has a field the schema does not know."""


class _CannotCoerce(ValueError):
    pass


@dataclass
class DriftReport:
    """Counts of every deviation seen while conforming a batch of rows."""

    rows: int = 0
    missing: Counter[str] = field(default_factory=Counter)
    coerced: Counter[tuple[str, str]] = field(default_factory=Counter)
    failed: Counter[tuple[str, str]] = field(default_factory=Counter)
    unexpected: Counter[str] = field(default_factory=Counter)

    @property
    def clean(self) -> bool:
        return not (self.missing or self.coerced or self.failed or self.unexpected)

    def lines(self) -> list[str]:
        out = [f"rows: {self.rows}"]
        for col, n in sorted(self.missing.items()):
            out.append(f"missing     {col}: {n}")
        for (col, src), n in sorted(self.coerced.items()):
            out.append(f"coerced     {col} from {src}: {n}")
        for (col, src), n in sorted(self.failed.items()):
            out.append(f"failed      {col} from {src}: {n}")
        for col, n in sorted(self.unexpected.items()):
            out.append(f"unexpected  {col}: {n}")
        return out


def type_name(value: Any) -> str:
    """The drift-report name of a Python value's type."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, Decimal):
        return "decimal"
    if isinstance(value, datetime):
        return "timestamp"
    if isinstance(value, date):
        return "date"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def infer_schema(rows: list[dict[str, Any]]) -> dict[str, Counter[str]]:
    """For each column, how many rows had each type. Drift shows up as >1 type."""
    seen: dict[str, Counter[str]] = {}
    for row in rows:
        for col, value in row.items():
            seen.setdefault(col, Counter())[type_name(value)] += 1
    return dict(sorted(seen.items()))


def coerce(value: Any, target: str) -> Any:
    """Convert `value` to `target` type, or raise if that would mean guessing."""
    if value is None:
        return None
    src = type_name(value)
    if target == "string":
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, (str, int, float, Decimal, bool)):
            return str(value)
    elif target == "int":
        if src == "int":
            return value
        if src == "float" and float(value).is_integer():
            return int(value)
        if src == "string" and value.strip().lstrip("-").isdigit():
            return int(value)
    elif target in ("float", "decimal"):
        if src in ("int", "float", "decimal", "string"):
            try:
                number = Decimal(str(value).strip())
            except InvalidOperation:
                raise _CannotCoerce(src) from None
            if not number.is_finite():
                raise _CannotCoerce(src)
            return float(number) if target == "float" else number.quantize(Decimal("0.01"))
    elif target == "bool":
        if src == "bool":
            return value
        if src == "string" and value.lower() in ("true", "false"):
            return value.lower() == "true"
        if src == "int" and value in (0, 1):
            return bool(value)
    elif target == "timestamp":
        if src == "timestamp":
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if src == "string":
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                raise _CannotCoerce(src) from None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    elif target == "date":
        if src == "date":
            return value
        if src == "timestamp":
            return value.date()
        if src == "string":
            try:
                return date.fromisoformat(value)
            except ValueError:
                raise _CannotCoerce(src) from None
    else:
        raise ValueError(f"unknown target type {target!r}; use one of {TYPES}")
    raise _CannotCoerce(src)


_NATIVE = {
    "string": ("string",),
    "int": ("int",),
    "float": ("float",),
    "decimal": ("decimal",),
    "bool": ("bool",),
    "timestamp": ("timestamp",),
    "date": ("date",),
}


def conform(
    rows: list[dict[str, Any]],
    schema: dict[str, str],
    on_new: OnNew = "rescue",
    report: DriftReport | None = None,
    optional: frozenset[str] = frozenset(),
) -> tuple[list[dict[str, Any]], DriftReport]:
    """Return rows with exactly the schema's columns (plus `_rescued`), and a report.

    Columns in `optional` may be absent by design (a loan sub-document exists only once
    an application is funded); their absence becomes NULL without being reported.
    """
    report = report or DriftReport()
    out: list[dict[str, Any]] = []
    for row in rows:
        report.rows += 1
        fixed: dict[str, Any] = {}
        for col, target in schema.items():
            if col not in row:
                if col not in optional:
                    report.missing[col] += 1
                fixed[col] = None
                continue
            value = row[col]
            src = type_name(value)
            if value is None:
                fixed[col] = None
                continue
            try:
                fixed[col] = coerce(value, target)
            except _CannotCoerce:
                report.failed[(col, src)] += 1
                fixed[col] = None
                continue
            if src not in _NATIVE[target] and not (target == "decimal" and src == "float"):
                report.coerced[(col, src)] += 1
        extra = {k: v for k, v in row.items() if k not in schema}
        for col in extra:
            report.unexpected[col] += 1
        if extra and on_new == "fail":
            raise SchemaDriftError(f"unexpected fields {sorted(extra)} in row {row}")
        if on_new == "rescue":
            fixed[RESCUED] = json.dumps(extra, default=str, sort_keys=True) if extra else None
        out.append(fixed)
    return out, report
