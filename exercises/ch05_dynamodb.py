"""Chapter 5 exercises: DynamoDB (DynamoDB Local).

Fill in each function, then run `make check-05` (DynamoDB Local must be up:
`make up-05`). `table` is a boto3 Table resource for a table with the same key layout
as the lab: PK and SK strings, payments stored as
    PK = "LOAN#<loan_id>", SK = "PAYMENT#<event_time ISO 8601>#<event_id>"
Reference answers: solutions/ch05_dynamodb.py.
"""

from __future__ import annotations

from typing import Any


def payments_between(table: Any, loan_id: str, start: str, end: str) -> list[dict[str, Any]]:
    """Exercise 5.1: one Query for a loan's payments in a date range.

    `start` and `end` are ISO dates like "2025-03-01" and "2025-06-30" (inclusive).
    Return the payment items, oldest first, using a key condition (not a filter and
    not a Scan). Remember a Query returns at most 1 MB per page.
    Hint: boto3.dynamodb.conditions.Key, and think about what string sorts just
    after every SK on the end date.
    """
    raise NotImplementedError


def put_if_absent(table: Any, item: dict[str, Any]) -> bool:
    """Exercise 5.2: write `item` only if no item with the same PK and SK exists.

    Return True if written, False if it already existed. Any other error must still
    raise.
    """
    raise NotImplementedError


def set_status_if_version(table: Any, key: dict[str, str], new_status: str, expected_version: int) -> bool:
    """Exercise 5.3: optimistic locking.

    Set `status` to `new_status` and increase `version` by 1, but only if the item's
    current `version` equals `expected_version`. Return True if the update happened,
    False if another writer got there first. (`status` is a reserved word in
    DynamoDB expressions, so use an expression attribute name for it.)
    """
    raise NotImplementedError


def export_items(table: Any, total_segments: int) -> list[dict[str, Any]]:
    """Exercise 5.4: export a whole table with a parallel scan.

    Scan the table in `total_segments` segments (Segment=0..n-1), following
    LastEvaluatedKey until each segment is finished, and return every item. Threads
    are optional; correctness is not.
    """
    raise NotImplementedError
