"""Chapter 7 reference solutions. Check them with `make check-07 SOLUTIONS=1`."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from typing import Any


def dpd_bucket(days_past_due: int | None) -> str:
    if days_past_due is None or days_past_due == 0:
        return "current"
    if days_past_due < 0:
        raise ValueError(f"days_past_due cannot be negative: {days_past_due}")
    if days_past_due < 30:
        return "1-29"
    if days_past_due < 60:
        return "30-59"
    if days_past_due < 90:
        return "60-89"
    return "90+"


def order_independent_checksum(rows: Iterable[Sequence[Any]]) -> int:
    # Addition modulo 2**64 is order-independent, and a duplicated row adds its hash
    # twice. XOR would cancel a duplicated row out (h ^ h == 0) and hide it.
    total = 0
    for row in rows:
        text = "\x1f".join(str(v) for v in row)
        h = int.from_bytes(hashlib.blake2b(text.encode(), digest_size=8).digest(), "big")
        total = (total + h) % 2**64
    return total


def days_to_extract(
    last_extracted: date | None, as_of: date, lookback_days: int, go_live: date
) -> list[date]:
    start = (
        go_live if last_extracted is None else max(go_live, last_extracted - timedelta(days=lookback_days))
    )
    return [start + timedelta(days=i) for i in range((as_of - start).days + 1)]


def rate_30_plus_by_product_sql(fct_loan_path: str) -> str:
    return f"""
        SELECT product,
               count(*) AS loans,
               count(*) FILTER (WHERE days_past_due >= 30) AS loans_30_plus,
               round(count(*) FILTER (WHERE days_past_due >= 30) / count(*), 4) AS rate_30_plus
        FROM '{fct_loan_path}'
        GROUP BY product
        ORDER BY product
    """
