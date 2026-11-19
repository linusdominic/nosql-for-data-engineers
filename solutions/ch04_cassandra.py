"""Chapter 4 reference solutions: Cassandra. Check them with `make check-04 SOLUTIONS=1`."""

from __future__ import annotations

import itertools
from typing import Any

MIN_TOKEN = -(2**63)
MAX_TOKEN = 2**63 - 1


def payments_by_borrower_month_ddl() -> str:
    # Partition key (borrower_id, month): one query reads exactly one partition, and a
    # partition never grows beyond one borrower's payments in one month.
    # Clustering key (event_time DESC, event_id): newest first, and event_id keeps two
    # payments with the same timestamp from overwriting each other.
    return """
        CREATE TABLE payments_by_borrower_month (
            borrower_id  text,
            month        text,
            event_time   timestamp,
            event_id     uuid,
            loan_id      text,
            amount_cents bigint,
            PRIMARY KEY ((borrower_id, month), event_time, event_id)
        ) WITH CLUSTERING ORDER BY (event_time DESC, event_id ASC)
    """


def token_ranges(n: int) -> list[tuple[int, int]]:
    width = (MAX_TOKEN - MIN_TOKEN) // n
    bounds = [MIN_TOKEN + i * width for i in range(n)] + [MAX_TOKEN]
    return list(itertools.pairwise(bounds))


def scan_by_token(session: Any, table: str, partition_key: str, n: int) -> list[Any]:
    query = session.prepare(
        f"SELECT * FROM {table} WHERE token({partition_key}) > ? AND token({partition_key}) <= ?"
    )
    rows: list[Any] = []
    for start, end in token_ranges(n):
        rows.extend(session.execute(query, (start, end)))
    return rows


def claim_payment(session: Any, event_id: Any, loan_id: str) -> bool:
    result = session.execute(
        "INSERT INTO payment_claims (event_id, loan_id) VALUES (%s, %s) IF NOT EXISTS",
        (event_id, loan_id),
    )
    return bool(result.was_applied)
