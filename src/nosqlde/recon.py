"""Reconcile a source against the lake with counts and order-independent checksums.

A count tells you whether rows went missing or were duplicated. It does not tell you
whether a value changed. A checksum does: hash each row's canonical text, then combine
the hashes with addition modulo 2**64. Addition does not care about order, so the
source can be read in token order and the lake in file order and the totals still match.

Canonical text matters more than the hash. The same instant must print the same way on
both sides (UTC, microseconds), the same amount the same way (no trailing zeros), and NULL
must be distinguishable from an empty string. `canonical` does that.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

MOD = 2**64


def canonical(value: Any) -> str:
    """One stable text form per value, shared by both sides of a reconciliation."""
    if value is None:
        return "\\N"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return str(value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (float, Decimal)):
        # 12500.0 (a double) and Decimal("12500.00") are the same amount: normalise both.
        return format(Decimal(str(value)).normalize(), "f")
    return str(value)


def row_hash(values: Sequence[Any]) -> int:
    text = "\x1f".join(canonical(v) for v in values)
    return int.from_bytes(hashlib.blake2b(text.encode(), digest_size=8).digest(), "big")


@dataclass(frozen=True)
class Fingerprint:
    """Row count plus order-independent checksum of a set of rows."""

    count: int
    checksum: int

    def __str__(self) -> str:
        return f"{self.count} rows, checksum {self.checksum:016x}"


def fingerprint(rows: Iterable[Sequence[Any]]) -> Fingerprint:
    count, total = 0, 0
    for values in rows:
        count += 1
        total = (total + row_hash(values)) % MOD
    return Fingerprint(count, total)


@dataclass(frozen=True)
class ReconResult:
    name: str
    source: Fingerprint
    lake: Fingerprint

    @property
    def ok(self) -> bool:
        return self.source == self.lake

    def line(self) -> str:
        status = "OK  " if self.ok else "FAIL"
        diff = self.lake.count - self.source.count
        detail = "" if self.ok else f"  (lake - source = {diff:+d} rows)"
        return (
            f"{status} {self.name:<42} source {self.source.count:>7}  "
            f"lake {self.lake.count:>7}  checksum {'match' if self.ok else 'MISMATCH'}{detail}"
        )


def reconcile(
    name: str, source_rows: Iterable[Sequence[Any]], lake_rows: Iterable[Sequence[Any]]
) -> ReconResult:
    return ReconResult(name, fingerprint(source_rows), fingerprint(lake_rows))
