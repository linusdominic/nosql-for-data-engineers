"""Chapter 7 exercises: the capstone's building blocks.

Fill in each function, then run `make check-07`. Exercises 7.1 to 7.3 need no
database. Exercise 7.4 reads lake/capstone/marts/fct_loan.parquet, so run
`make capstone` first. Reference answers: solutions/ch07_capstone.py.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any


def dpd_bucket(days_past_due: int | None) -> str:
    """Exercise 7.1: the delinquency bucket used in mart_delinquency.

    None or 0 -> "current"; 1..29 -> "1-29"; 30..59 -> "30-59"; 60..89 -> "60-89";
    90 or more -> "90+". Negative values are a data error: raise ValueError.
    """
    raise NotImplementedError


def order_independent_checksum(rows: Iterable[Sequence[Any]]) -> int:
    """Exercise 7.2: a checksum for reconciliation.

    Hash each row (join str(value) for each value with a separator nobody uses, such
    as "\\x1f", and take the first 8 bytes of hashlib.blake2b as an int), then combine
    the hashes so that the result does not depend on row order but DOES change when
    a row is duplicated or missing. Return an int in [0, 2**64).
    Think about why XOR would be the wrong way to combine them.
    """
    raise NotImplementedError


def days_to_extract(
    last_extracted: date | None, as_of: date, lookback_days: int, go_live: date
) -> list[date]:
    """Exercise 7.3: which Cassandra day partitions should this run (re)read?

    First run (last_extracted is None): every day from go_live to as_of.
    Later runs: from (last_extracted - lookback_days) to as_of, but never before
    go_live. Both ends inclusive, in date order.
    """
    raise NotImplementedError


def rate_30_plus_by_product_sql(fct_loan_path: str) -> str:
    """Exercise 7.4: a DuckDB query over the fct_loan Parquet file.

    Return SQL that produces columns product, loans, loans_30_plus, rate_30_plus
    (loans_30_plus / loans rounded to 4 places), one row per product, ordered by
    product. A loan is "30 plus" if days_past_due >= 30. Read the file with
    FROM '<fct_loan_path>'.
    """
    raise NotImplementedError
