"""Chapter 6 exercises: Neo4j.

Fill in each function, then run `make check-06` (Neo4j must be up: `make up-06`).
The check loads the lab's graph first:

    (:Person {borrower_id})-[:SUBMITTED]->(:Application {application_id, status, product})
    (:Application)-[:USES_PHONE]->(:Phone {number})
    (:Application)-[:USES_DEVICE]->(:Device {device_id})
    (:Application)-[:AT_ADDRESS]->(:Address {key})

Reference answers: solutions/ch06_neo4j.py.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from neo4j import Driver


def shared_device_query() -> str:
    """Exercise 6.1: write a Cypher query.

    Return pairs of applications submitted by *different* people that used the same
    device, each pair once (a1 < a2), as columns a1, a2, device_id, ordered by a1, a2.
    """
    raise NotImplementedError


def connected_applications(driver: Driver, application_id: str, max_hops: int) -> list[str]:
    """Exercise 6.2: multi-hop traversal.

    Return the sorted application ids reachable from `application_id` through any
    chain of shared phones, devices or addresses of at most `max_hops` relationships,
    including `application_id` itself. Hint: variable-length patterns cannot take a
    parameter for the length, so build the query string with the number in it.
    """
    raise NotImplementedError


def group_by_shared_identifiers(pairs: Iterable[tuple[str, str]]) -> list[list[str]]:
    """Exercise 6.3: connected components in plain Python.

    `pairs` are (application_id, identifier) rows such as ("A0000030", "phone:+999 7...").
    Two applications are in the same group if they share an identifier, directly or
    through a chain of other applications. Return every group as a sorted list, and
    the list of groups sorted by its first element. Include groups of one.
    Write it yourself (union-find, or a breadth-first search); do not call nosqlde.graph.
    """
    raise NotImplementedError


def export_edges(driver: Driver, path: Path) -> int:
    """Exercise 6.4: export the graph's identity edges to a Parquet file.

    Write one row per USES_PHONE, USES_DEVICE or AT_ADDRESS relationship, with
    string columns application_id, kind (the relationship type) and value (the
    phone number, device id or address key). Return the number of rows written.
    Hint: pyarrow.Table.from_pylist and pyarrow.parquet.write_table.
    """
    raise NotImplementedError
