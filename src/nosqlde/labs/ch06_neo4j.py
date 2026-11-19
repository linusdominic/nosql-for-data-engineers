"""Chapter 6 lab: Neo4j, a graph database, and a fraud-ring use case.

Run with `make lab-06` (Neo4j must be up: `make up-06`). The lab deletes every node
in the default `neo4j` database first, so it is safe to re-run.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import duckdb
from neo4j import Driver
from neo4j.exceptions import Neo4jError

from nosqlde import clients, datagen, graph, lake
from nosqlde.config import SETTINGS
from nosqlde.console import heading, say, step, table

EDGE_SCHEMA = {"application_id": "string", "borrower_id": "string", "kind": "string", "value": "string"}


def identity_rows(world: datagen.World) -> list[dict[str, Any]]:
    """One row per application with the identifiers it used."""
    rows = []
    for doc in datagen.applications_as_of(world, world.as_of):
        a = doc["address"]
        rows.append(
            {
                "application_id": doc["application_id"],
                "borrower_id": doc["borrower"]["borrower_id"],
                "name": doc["borrower"]["full_name"],
                "status": doc["status"],
                "product": doc["product"],
                "submitted_at": doc["submitted_at"].isoformat(),
                "phone": doc["contact"]["phone"],
                "device_id": doc["device_id"],
                "address_key": f"{a['line1']}, {a['town']}, {a['postcode']}",
            }
        )
    return rows


LOAD = """
UNWIND $rows AS r
MERGE (p:Person {borrower_id: r.borrower_id}) ON CREATE SET p.name = r.name
MERGE (a:Application {application_id: r.application_id})
  SET a.status = r.status, a.product = r.product, a.submitted_at = datetime(r.submitted_at)
MERGE (p)-[:SUBMITTED]->(a)
MERGE (ph:Phone {number: r.phone})
MERGE (a)-[:USES_PHONE]->(ph)
MERGE (d:Device {device_id: r.device_id})
MERGE (a)-[:USES_DEVICE]->(d)
MERGE (ad:Address {key: r.address_key})
MERGE (a)-[:AT_ADDRESS]->(ad)
"""

CONSTRAINTS = [
    "CREATE CONSTRAINT person_id IF NOT EXISTS FOR (n:Person) REQUIRE n.borrower_id IS UNIQUE",
    "CREATE CONSTRAINT application_id IF NOT EXISTS FOR (n:Application) REQUIRE n.application_id IS UNIQUE",
    "CREATE CONSTRAINT phone_number IF NOT EXISTS FOR (n:Phone) REQUIRE n.number IS UNIQUE",
    "CREATE CONSTRAINT device_id IF NOT EXISTS FOR (n:Device) REQUIRE n.device_id IS UNIQUE",
    "CREATE CONSTRAINT address_key IF NOT EXISTS FOR (n:Address) REQUIRE n.key IS UNIQUE",
]

EDGES = """
MATCH (p:Person)-[:SUBMITTED]->(a:Application)-[r:USES_PHONE|USES_DEVICE|AT_ADDRESS]->(x)
RETURN a.application_id AS application_id, p.borrower_id AS borrower_id,
       type(r) AS kind, coalesce(x.number, x.device_id, x.key) AS value
"""


def reset(driver: Driver) -> None:
    """Delete everything. CALL ... IN TRANSACTIONS needs an auto-commit (implicit)
    transaction, so it goes through session.run, not execute_query."""
    with driver.session() as session:
        session.run("MATCH (n) CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 5000 ROWS").consume()


def load(driver: Driver, rows: list[dict[str, Any]], batch: int = 500) -> None:
    for stmt in CONSTRAINTS:
        driver.execute_query(stmt)
    for i in range(0, len(rows), batch):
        driver.execute_query(LOAD, rows=rows[i : i + batch])


def _walk(plan: Any) -> Iterator[Any]:
    yield plan
    for child in plan.get("children", []):
        yield from _walk(child)


def profile(driver: Driver, query: str, **params: Any) -> tuple[str, int, int]:
    """(operators, total db hits, rows) from PROFILE."""
    result = driver.execute_query("PROFILE " + query, **params)
    plan = result.summary.profile or {}
    ops = [p["operatorType"].split("@")[0] for p in _walk(plan)]
    hits = sum(p.get("dbHits", 0) for p in _walk(plan))
    return " <- ".join(ops), hits, len(result.records)


def run() -> None:
    heading("Chapter 6 lab: Neo4j")
    driver = clients.neo4j()
    world = datagen.generate(seed=42)
    out = SETTINGS.lake_dir / "ch06"
    rows = identity_rows(world)
    edition = driver.execute_query(
        "CALL dbms.components() YIELD versions, edition RETURN versions[0] AS v, edition"
    ).records[0]
    say(f"Neo4j {edition['v']} {edition['edition']} edition")

    # ------------------------------------------------------------------ 6.1
    step("6.1", "Constraints, and what Community edition does not have")
    reset(driver)
    for stmt in CONSTRAINTS:
        driver.execute_query(stmt)
    say(f"created {len(CONSTRAINTS)} uniqueness constraints (each one is backed by an index)")
    try:
        driver.execute_query(
            "CREATE CONSTRAINT app_status_exists IF NOT EXISTS FOR (n:Application) REQUIRE n.status IS NOT NULL"
        )
    except Neo4jError as err:
        text = " ".join((err.message or "").split())
        reason = text[text.find("requires") :] if "requires" in text else text[:160]
        say(f"property existence constraint -> {err.code}: ...{reason[:90]}")

    # ------------------------------------------------------------------ 6.2
    step("6.2", "Load nodes and relationships with UNWIND + MERGE")
    start = time.perf_counter()
    load(driver, rows)
    took = time.perf_counter() - start
    labels = driver.execute_query(
        "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY label"
    ).records
    rels = driver.execute_query(
        "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n ORDER BY type"
    ).records
    say(f"loaded {len(rows)} applications in {took:.1f}s (batches of 500)")
    table([[r["label"], r["n"]] for r in labels], ["node label", "count"])
    table([[r["type"], r["n"]] for r in rels], ["relationship type", "count"])

    # ------------------------------------------------------------------ 6.3
    step("6.3", "Cypher pattern versus SQL self-join")
    cypher = """
        MATCH (p1:Person)-[:SUBMITTED]->(a1:Application)-[:USES_PHONE]->(ph:Phone)
              <-[:USES_PHONE]-(a2:Application)<-[:SUBMITTED]-(p2:Person)
        WHERE a1.application_id < a2.application_id AND p1 <> p2
        RETURN a1.application_id AS a1, a2.application_id AS a2, ph.number AS phone
        ORDER BY a1, a2
    """
    pairs = driver.execute_query(cypher).records
    edges = [dict(r) for r in driver.execute_query(EDGES).records]
    lake.write_parquet(edges, out / "edges.parquet", lake.arrow_schema(EDGE_SCHEMA))
    sql = f"""
        SELECT e1.application_id AS a1, e2.application_id AS a2, e1.value AS phone
        FROM '{out}/edges.parquet' e1
        JOIN '{out}/edges.parquet' e2
          ON e1.kind = 'USES_PHONE' AND e2.kind = 'USES_PHONE' AND e1.value = e2.value
         AND e1.application_id < e2.application_id AND e1.borrower_id <> e2.borrower_id
        ORDER BY a1, a2
    """
    sql_pairs = duckdb.connect().execute(sql).fetchall()
    say(f"Cypher: {len(pairs)} pairs of applications by different people sharing a phone")
    say(
        f"SQL self-join over the exported edge table: {len(sql_pairs)} pairs; identical: "
        f"{[tuple(r.values()) for r in pairs] == sql_pairs}"
    )
    table([list(r.values()) for r in pairs[:3]], ["a1", "a2", "phone"])

    # ------------------------------------------------------------------ 6.4
    step("6.4", "Multi-hop traversal: everything connected to one application")
    seed = world.rings[0][0]
    ring_query = """
        MATCH (start:Application {application_id: $id})
              -[:USES_PHONE|USES_DEVICE|AT_ADDRESS*1..10]-(other:Application)
        RETURN DISTINCT other.application_id AS id ORDER BY id
    """
    found = sorted({seed} | {r["id"] for r in driver.execute_query(ring_query, id=seed).records})
    say(f"applications reachable from {seed} through shared phones, devices or addresses: {found}")
    say(f"planted ring (ground truth from the generator): {world.rings[0]}")
    recursive = f"""
        WITH RECURSIVE reach(application_id) AS (
            SELECT '{seed}'
            UNION
            SELECT e2.application_id
            FROM reach r
            JOIN '{out}/edges.parquet' e1 ON e1.application_id = r.application_id
            JOIN '{out}/edges.parquet' e2 ON e2.kind = e1.kind AND e2.value = e1.value
        )
        SELECT application_id FROM reach ORDER BY 1
    """
    via_sql = [r[0] for r in duckdb.connect().execute(recursive).fetchall()]
    say(f"the same question as a recursive CTE in DuckDB: {via_sql}")
    ring_people = {r["borrower_id"] for r in rows if r["application_id"] in world.rings[0]}
    for extra in sorted(set(found) - set(world.rings[0])):
        who = next(r["borrower_id"] for r in rows if r["application_id"] == extra)
        say(
            f"  {extra} is not in the planted ring: borrower {who} "
            f"{'also submitted a ring application' if who in ring_people else 'is linked through a ring member'}"
        )

    # ------------------------------------------------------------------ 6.5
    step("6.5", "Shortest path between two members")
    a, b = world.rings[0][0], world.rings[0][-1]
    path = driver.execute_query(
        """
        MATCH p = shortestPath((x:Application {application_id: $a})
                  -[:USES_PHONE|USES_DEVICE|AT_ADDRESS*..12]-(y:Application {application_id: $b}))
        RETURN [n IN nodes(p) | coalesce(n.application_id, labels(n)[0])] AS hops,
               [r IN relationships(p) | type(r)] AS rels
        """,
        a=a,
        b=b,
    ).records[0]
    say(f"{a} to {b}: {len(path['rels'])} relationships")
    say("  " + " - ".join(path["hops"]))

    # ------------------------------------------------------------------ 6.6
    step("6.6", "PROFILE: index seek versus label scan")
    p1 = profile(driver, "MATCH (a:Application {application_id: $id}) RETURN a", id=seed)
    p2 = profile(driver, "MATCH (a:Application {product: 'auto', status: 'declined'}) RETURN a")
    table(
        [["by application_id (unique constraint)", *p1], ["by product and status (no index)", *p2]],
        ["lookup", "operators", "db hits", "rows"],
    )

    # ------------------------------------------------------------------ 6.7
    step("6.7", "Rings across the whole graph: export edges, then connected components")
    comps = graph.components_from_shared_keys(
        (e["application_id"], f"{e['kind']}:{e['value']}") for e in edges
    )
    borrower_of = {e["application_id"]: e["borrower_id"] for e in edges}
    sizes: dict[int, int] = {}
    flagged = []
    for cid, members in comps.items():
        sizes[len(members)] = sizes.get(len(members), 0) + 1
        people = {borrower_of[m] for m in members}
        if len(people) >= 3:
            flagged.append((cid, members, len(people)))
    say("component sizes (applications per component: how many components):")
    say("  " + ", ".join(f"{k}: {v}" for k, v in sorted(sizes.items())))
    contained = sum(1 for ring in world.rings if any(set(ring) <= set(m) for _, m, _ in flagged))
    false_alarms = sum(1 for _, m, _ in flagged if not any(set(r) <= set(m) for r in world.rings))
    ring_apps = {a for r in world.rings for a in r}
    ring_borrowers = {borrower_of[a] for a in ring_apps}
    extra = [m for _, ms, _ in flagged for m in ms if m not in ring_apps]
    say(
        f"components with 3 or more distinct borrowers: {len(flagged)}; planted rings: {len(world.rings)}; "
        f"rings found whole inside a flagged component: {contained}; flagged components with no ring: {false_alarms}"
    )
    say(
        f"flagged applications: {len(ring_apps) + len(extra)} = {len(ring_apps)} planted + {len(extra)} extra "
        f"({sum(borrower_of[m] in ring_borrowers for m in extra)} are other applications by ring borrowers, "
        f"{sum(borrower_of[m] not in ring_borrowers for m in extra)} belong to people linked to a ring member)"
    )
    pairs_2 = sum(1 for m in comps.values() if len(m) == 2)
    say(
        f"components of 2 (households sharing an address, or one person applying twice): {pairs_2}; not flagged"
    )

    # ------------------------------------------------------------------ 6.8
    step("6.8", "Graph results as tables")
    ring_rows = [
        {"ring_id": cid, "application_id": m, "borrower_id": borrower_of[m], "ring_size": len(ms)}
        for cid, ms, _ in flagged
        for m in ms
    ]
    ring_schema = {
        "ring_id": "string",
        "application_id": "string",
        "borrower_id": "string",
        "ring_size": "int",
    }
    lake.write_parquet(ring_rows, out / "ring_members.parquet", lake.arrow_schema(ring_schema))
    status = (
        duckdb.connect()
        .execute(
            f"""
        SELECT r.ring_id, any_value(r.ring_size) AS size,
               string_agg(DISTINCT e.kind, ', ' ORDER BY e.kind) AS linked_by
        FROM '{out}/ring_members.parquet' r
        JOIN '{out}/edges.parquet' e USING (application_id)
        WHERE (e.kind, e.value) IN (
            SELECT kind, value FROM '{out}/edges.parquet' GROUP BY kind, value
            HAVING count(DISTINCT borrower_id) > 1)
        GROUP BY r.ring_id ORDER BY r.ring_id
        """
        )
        .fetchall()
    )
    say(f"wrote {out}/edges.parquet ({len(edges)} rows) and ring_members.parquet ({len(ring_rows)} rows)")
    table(status, ["ring_id", "applications", "linked by"])
    driver.close()
