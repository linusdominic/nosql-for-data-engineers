"""Chapter 6 reference solutions: Neo4j. Check them with `make check-06 SOLUTIONS=1`."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from neo4j import Driver


def shared_device_query() -> str:
    return """
        MATCH (p1:Person)-[:SUBMITTED]->(a1:Application)-[:USES_DEVICE]->(d:Device)
              <-[:USES_DEVICE]-(a2:Application)<-[:SUBMITTED]-(p2:Person)
        WHERE a1.application_id < a2.application_id AND p1 <> p2
        RETURN a1.application_id AS a1, a2.application_id AS a2, d.device_id AS device_id
        ORDER BY a1, a2
    """


def connected_applications(driver: Driver, application_id: str, max_hops: int) -> list[str]:
    query = f"""
        MATCH (s:Application {{application_id: $id}})
              -[:USES_PHONE|USES_DEVICE|AT_ADDRESS*1..{int(max_hops)}]-(o:Application)
        RETURN DISTINCT o.application_id AS id
    """
    found = {r["id"] for r in driver.execute_query(query, id=application_id).records}
    return sorted(found | {application_id})


def group_by_shared_identifiers(pairs: Iterable[tuple[str, str]]) -> list[list[str]]:
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    apps: set[str] = set()
    for app, key in pairs:
        apps.add(app)
        a, k = find("a:" + app), find("k:" + key)
        if a != k:
            parent[k] = a
    groups: dict[str, list[str]] = {}
    for app in apps:
        groups.setdefault(find("a:" + app), []).append(app)
    return sorted(sorted(g) for g in groups.values())


def export_edges(driver: Driver, path: Path) -> int:
    records = driver.execute_query(
        """
        MATCH (a:Application)-[r:USES_PHONE|USES_DEVICE|AT_ADDRESS]->(x)
        RETURN a.application_id AS application_id, type(r) AS kind,
               coalesce(x.number, x.device_id, x.key) AS value
        """
    ).records
    rows = [dict(r) for r in records]
    schema = pa.schema([("application_id", pa.string()), ("kind", pa.string()), ("value", pa.string())])
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
    return len(rows)
