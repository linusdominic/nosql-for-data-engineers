"""Chapter 6 in the studio: Neo4j, in a Cypher console, plus DuckDB for the SQL comparison."""

from __future__ import annotations

from typing import Any

from nosqlde.studio.checking import CheckRun, Outcome, failed, passed
from nosqlde.studio.lessons.model import Custom, Example, Exercise, GuideRef, Lesson, Match, Step
from nosqlde.studio.lessons.prepare import prepare_neo4j
from nosqlde.studio.runners.base import RunResult

SHARED_PHONE = """MATCH (p1:Person)-[:SUBMITTED]->(a1:Application)-[:USES_PHONE]->(ph:Phone)
      <-[:USES_PHONE]-(a2:Application)<-[:SUBMITTED]-(p2:Person)
WHERE a1.application_id < a2.application_id AND p1 <> p2
RETURN a1.application_id AS a1, a2.application_id AS a2, ph.number AS phone
ORDER BY a1, a2"""

RING = """MATCH (start:Application {application_id: 'A0000030'})
      -[:USES_PHONE|USES_DEVICE|AT_ADDRESS*1..10]-(other:Application)
RETURN DISTINCT other.application_id AS id"""


def _profile(answer: RunResult) -> dict[str, Any] | None:
    last = answer.last
    if (
        last is None
        or last.kind != "plan"
        or not isinstance(last.data, dict)
        or not last.data.get("profiled")
    ):
        return None
    return last.data


def check_seek(run: CheckRun, answer: RunResult) -> Outcome:
    data = _profile(answer)
    if data is None:
        return failed("Prefix the query with PROFILE, so the check can read the plan and its db hits.")
    plan = data["plan"]
    records = data["records"]
    expected = {"operators": "ProduceResults <- NodeUniqueIndexSeek", "rows": 1}
    got = {"operators": plan["operators"], "rows": plan["rows"], "db hits": plan["total_db_hits"]}
    ids = [r.get("a", {}).get("application_id") if isinstance(r.get("a"), dict) else None for r in records]
    if "NodeUniqueIndexSeek" not in plan["operators"]:
        return failed(
            "The plan does not seek the unique constraint's index. Match on the label and the key property: (a:Application {application_id: ...}).",
            expected,
            got,
        )
    if plan["rows"] != 1 or ids != ["A0000030"]:
        return failed("Return the application node as a: one row, application A0000030.", expected, got)
    return passed(f"NodeUniqueIndexSeek: {plan['total_db_hits']} db hits for one row.", expected, got)


def check_index_seek(run: CheckRun, answer: RunResult) -> Outcome:
    data = _profile(answer)
    if data is None:
        return failed("End with the PROFILE of the lookup, so the check can read the plan.")
    plan = data["plan"]
    want = run.last("MATCH (a:Application {product: 'auto', status: 'declined'}) RETURN count(a) AS n").data
    n = want[0]["n"] if isinstance(want, list) and want else None
    expected = {"operators": "... NodeIndexSeek ...", "rows": n}
    got = {"operators": plan["operators"], "rows": plan["rows"], "db hits": plan["total_db_hits"]}
    if plan["rows"] != n:
        return failed(
            f"The query returned {plan['rows']} rows; auto applications that were declined are {n}.",
            expected,
            got,
        )
    if "NodeByLabelScan" in plan["operators"] or "IndexSeek" not in plan["operators"]:
        return failed(
            "The plan still scans every Application node. Create an index on Application.status first, in the same run.",
            expected,
            got,
        )
    return passed(
        f"{plan['operators']}: {plan['total_db_hits']} db hits instead of a label scan.", expected, got
    )


LESSON = Lesson(
    id="ch06",
    number=6,
    title="Graph with Neo4j",
    database="Neo4j 5.26",
    summary="Cypher patterns versus joins, multi-hop fraud rings, shortest paths, PROFILE, and graph results as tables.",
    guide=GuideRef(6, "6. Graph with Neo4j"),
    consoles=("cypher", "duckdb"),
    services=("neo4j",),
    make_up="make up-06",
    prepare=prepare_neo4j,
    prepare_note="Deletes every node in Neo4j (Community has one database, shared with the lab, the check and the capstone), reloads the lab's identity graph and writes lake/studio/ch06/edges.parquet.",
    steps=(
        Step(
            id="model",
            title="The model, and loading it",
            guide=GuideRef(6, "Loading: `UNWIND` plus `MERGE`"),
            prose=(
                "A graph stores **nodes** with labels and **relationships** with a type and a direction; both have properties. Here: `(:Person)-[:SUBMITTED]->(:Application)`, and each application `USES_PHONE`, `USES_DEVICE` and is `AT_ADDRESS`.",
                "Prepare loaded the graph with the lab's `UNWIND $rows ... MERGE` query, after creating uniqueness constraints. Fewer phones (1,993) than applications (2,393) is the interesting part: some applications share a phone.",
                "The console runs Cypher; separate statements with `;`.",
            ),
            examples=(
                Example(
                    "Relationships by type",
                    "cypher",
                    "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n ORDER BY type",
                ),
                Example(
                    "The constraints", "cypher", "SHOW CONSTRAINTS YIELD name, labelsOrTypes, properties"
                ),
                Example(
                    "One application and its identifiers",
                    "cypher",
                    "MATCH (a:Application {application_id: 'A0000030'})-[r]-(x)\nRETURN type(r) AS rel, labels(x)[0] AS kind, coalesce(x.number, x.device_id, x.key, x.borrower_id) AS value",
                ),
            ),
            exercises=(
                Exercise(
                    id="ch06.labels",
                    number="6.1",
                    title="Count the nodes by label",
                    console="cypher",
                    task="Return one row per node label with `label` and `n` (how many nodes have it).",
                    starter="MATCH (n:Application) RETURN count(*) AS n",
                    hints=(
                        "Match every node: MATCH (n).",
                        "labels(n) is a list; every node here has one label: labels(n)[0].",
                        "Grouping is implicit: RETURN labels(n)[0] AS label, count(*) AS n",
                    ),
                    solution="MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n",
                    check=Match(fields=("label", "n")),
                    wrong=(
                        "MATCH (n:Application) RETURN labels(n)[0] AS label, count(*) AS n",
                        "MATCH ()-[r]->() RETURN type(r) AS label, count(*) AS n",
                    ),
                    explain="Address 1940, Application 2393, Device 1998, Person 2000, Phone 1993: the guide's step 6.2.",
                ),
            ),
        ),
        Step(
            id="patterns",
            title="Cypher patterns versus SQL joins",
            guide=GuideRef(6, "Cypher patterns versus SQL joins"),
            prose=(
                'In Cypher you draw the pattern; in SQL you self-join an edge table. "Pairs of applications by different people that share a phone" is one `MATCH`.',
                "Prepare also exported the identity edges to `lake/studio/ch06/edges.parquet` (columns `application_id`, `borrower_id`, `kind`, `value`), so you can write the same question in SQL in the DuckDB console.",
            ),
            examples=(
                Example("Shared phones, in Cypher", "cypher", SHARED_PHONE),
                Example(
                    "The exported edges",
                    "duckdb",
                    "SELECT kind, count(*) AS edges FROM 'lake/studio/ch06/edges.parquet' GROUP BY kind ORDER BY kind",
                ),
            ),
            exercises=(
                Exercise(
                    id="ch06.device",
                    number="6.2",
                    title="Applications sharing a device",
                    console="cypher",
                    task="Return the pairs of applications by different people that share a device: `a1`, `a2` (with a1 < a2) and `device_id`.",
                    starter="MATCH (a1:Application)-[:USES_DEVICE]->(d:Device)<-[:USES_DEVICE]-(a2:Application)\nRETURN a1.application_id AS a1, a2.application_id AS a2, d.device_id AS device_id",
                    hints=(
                        "Each pair appears twice and an application pairs with itself: add a1.application_id < a2.application_id.",
                        "Different people: bring in (p1:Person)-[:SUBMITTED]-> and (p2:Person)-[:SUBMITTED]->, then p1 <> p2.",
                        "Follow the shared-phone example and swap the relationship and node label.",
                    ),
                    solution=(
                        "MATCH (p1:Person)-[:SUBMITTED]->(a1:Application)-[:USES_DEVICE]->(d:Device)\n"
                        "      <-[:USES_DEVICE]-(a2:Application)<-[:SUBMITTED]-(p2:Person)\n"
                        "WHERE a1.application_id < a2.application_id AND p1 <> p2\n"
                        "RETURN a1.application_id AS a1, a2.application_id AS a2, d.device_id AS device_id"
                    ),
                    check=Match(fields=("a1", "a2", "device_id")),
                    wrong=(
                        "MATCH (a1:Application)-[:USES_DEVICE]->(d:Device)<-[:USES_DEVICE]-(a2:Application) WHERE a1.application_id < a2.application_id RETURN a1.application_id AS a1, a2.application_id AS a2, d.device_id AS device_id",
                        SHARED_PHONE.replace("ph.number AS phone", "ph.number AS device_id"),
                    ),
                    explain="8 pairs, the same answer as make check-06's exercise 6.1.",
                ),
                Exercise(
                    id="ch06.sql",
                    number="6.3",
                    title="The same question as a SQL self-join",
                    console="duckdb",
                    task=(
                        "In DuckDB, over `lake/studio/ch06/edges.parquet`, return the pairs of applications by different borrowers that share a phone "
                        "(`kind` = 'USES_PHONE'): columns `a1`, `a2` (a1 < a2) and `phone`."
                    ),
                    starter="SELECT e1.application_id AS a1, e2.application_id AS a2, e1.value AS phone\nFROM 'lake/studio/ch06/edges.parquet' e1\nJOIN 'lake/studio/ch06/edges.parquet' e2 ON e1.value = e2.value",
                    hints=(
                        "Both sides must be phone edges: e1.kind = 'USES_PHONE' AND e2.kind = 'USES_PHONE'.",
                        "Each pair once: e1.application_id < e2.application_id.",
                        "Different people: e1.borrower_id <> e2.borrower_id.",
                    ),
                    solution=(
                        "SELECT e1.application_id AS a1, e2.application_id AS a2, e1.value AS phone\n"
                        "FROM 'lake/studio/ch06/edges.parquet' e1\n"
                        "JOIN 'lake/studio/ch06/edges.parquet' e2\n"
                        "  ON e1.kind = 'USES_PHONE' AND e2.kind = 'USES_PHONE' AND e1.value = e2.value\n"
                        " AND e1.application_id < e2.application_id AND e1.borrower_id <> e2.borrower_id"
                    ),
                    check=Match(fields=("a1", "a2", "phone")),
                    wrong=(
                        "SELECT e1.application_id AS a1, e2.application_id AS a2, e1.value AS phone FROM 'lake/studio/ch06/edges.parquet' e1 JOIN 'lake/studio/ch06/edges.parquet' e2 ON e1.kind = 'USES_PHONE' AND e2.kind = 'USES_PHONE' AND e1.value = e2.value AND e1.application_id < e2.application_id",
                        "SELECT e1.application_id AS a1, e2.application_id AS a2, e1.value AS phone FROM 'lake/studio/ch06/edges.parquet' e1 JOIN 'lake/studio/ch06/edges.parquet' e2 ON e1.value = e2.value AND e1.application_id < e2.application_id AND e1.borrower_id <> e2.borrower_id",
                    ),
                    explain="11 pairs either way; the difference appears with depth, where SQL needs a recursive CTE.",
                ),
            ),
        ),
        Step(
            id="rings",
            title="A lending use case: fraud rings",
            guide=GuideRef(6, "A lending use case: fraud rings"),
            prose=(
                "The generator plants 8 fraud rings, chained so that no single identifier links a whole ring: member 1 shares a phone with member 2, who shares a device with member 3, and so on. Only a multi-hop traversal finds them.",
                "A variable-length pattern `-[:USES_PHONE|USES_DEVICE|AT_ADDRESS*1..10]-` follows any of the three relationship types, in either direction, up to 10 hops.",
            ),
            exercises=(
                Exercise(
                    id="ch06.ring",
                    number="6.4",
                    title="Everything connected to one application",
                    console="cypher",
                    task="Starting from application A0000030, return the distinct `application_id` (as `id`) of every application reachable through shared phones, devices or addresses, up to 10 hops.",
                    starter="MATCH (start:Application {application_id: 'A0000030'})-[:USES_PHONE]-(other:Application)\nRETURN DISTINCT other.application_id AS id",
                    hints=(
                        "One hop from an application reaches a phone, not another application: you need a variable-length pattern.",
                        "Combine relationship types with |: [:USES_PHONE|USES_DEVICE|AT_ADDRESS*1..10]",
                        "Leave the direction out (-[...]-), so the traversal goes both ways.",
                    ),
                    solution=RING,
                    check=Match(fields=("id",)),
                    wrong=(
                        RING.replace("*1..10", "*1..2"),
                        RING.replace("USES_PHONE|USES_DEVICE|AT_ADDRESS", "USES_PHONE"),
                    ),
                    explain="The planted ring plus three neighbours: links propagate to innocent applications, so a result is a list to investigate, not a verdict.",
                ),
                Exercise(
                    id="ch06.path",
                    number="6.5",
                    title="How two members are connected",
                    console="cypher",
                    task="Find the shortest path between applications A0000030 and A0001525 over the three identifier relationships (at most 12 hops) and return its length as `hops`.",
                    starter="MATCH p = (x:Application {application_id: 'A0000030'})-[:USES_PHONE|USES_DEVICE|AT_ADDRESS*..12]-(y:Application {application_id: 'A0001525'})\nRETURN length(p) AS hops LIMIT 1",
                    hints=(
                        "Wrap the pattern in shortestPath(...).",
                        "MATCH p = shortestPath((x ...)-[...*..12]-(y ...))",
                        "Return p as well to see the hops.",
                    ),
                    solution=(
                        "MATCH p = shortestPath((x:Application {application_id: 'A0000030'})\n"
                        "          -[:USES_PHONE|USES_DEVICE|AT_ADDRESS*..12]-(y:Application {application_id: 'A0001525'}))\n"
                        "RETURN length(p) AS hops"
                    ),
                    check=Match(fields=("hops",)),
                    wrong=(
                        "MATCH p = shortestPath((x:Application {application_id: 'A0000030'})-[:USES_PHONE*..12]-(y:Application {application_id: 'A0001525'})) RETURN length(p) AS hops",
                        "MATCH p = shortestPath((x:Application {application_id: 'A0000030'})-[:USES_PHONE|USES_DEVICE|AT_ADDRESS*..12]-(y:Application {application_id: 'A0000413'})) RETURN length(p) AS hops",
                    ),
                    explain="6 relationships: A0000030 - Device - A0000302 - Address - A0000413 - Phone - A0001525.",
                ),
            ),
        ),
        Step(
            id="profile",
            title="PROFILE: index seek versus label scan",
            guide=GuideRef(6, "`PROFILE`: index seek versus label scan"),
            prose=(
                "`PROFILE` runs a query and returns its plan with **db hits** (units of storage work), operator by operator; `EXPLAIN` shows the plan without running it. The console shows the operator tree, root first.",
                "The guide's step 6.6: a lookup by `application_id` seeks the unique constraint's index (6 db hits); a lookup by product and status reads every `Application` node and filters (6,468 db hits; the count varies by a few between runs).",
            ),
            examples=(
                Example(
                    "A label scan",
                    "cypher",
                    "PROFILE MATCH (a:Application {product: 'auto', status: 'declined'}) RETURN a",
                ),
                Example("Drop the index of exercise 6.7", "cypher", "DROP INDEX app_status IF EXISTS"),
            ),
            exercises=(
                Exercise(
                    id="ch06.seek",
                    number="6.6",
                    title="Seek through the constraint's index",
                    console="cypher",
                    task="PROFILE the lookup of application A0000030 by `application_id`, returning the node as `a`. The check wants a `NodeUniqueIndexSeek`.",
                    starter="MATCH (a {application_id: 'A0000030'}) RETURN a",
                    hints=(
                        "Prefix the query with PROFILE.",
                        "Without a label, Neo4j cannot use the label's index: it scans all nodes.",
                        "PROFILE MATCH (a:Application {application_id: 'A0000030'}) RETURN a",
                    ),
                    solution="PROFILE MATCH (a:Application {application_id: 'A0000030'}) RETURN a",
                    check=Custom(check_seek),
                    wrong=(
                        "MATCH (a:Application {application_id: 'A0000030'}) RETURN a",
                        "PROFILE MATCH (a {application_id: 'A0000030'}) RETURN a",
                    ),
                    explain="Same reading as MongoDB's explain(): a seek through an index versus reading everything.",
                ),
                Exercise(
                    id="ch06.index",
                    number="6.7",
                    title="Index what you filter on",
                    console="cypher",
                    task=(
                        "Create an index named `app_status` on `Application.status`, then PROFILE "
                        "`MATCH (a:Application {product: 'auto', status: 'declined'}) RETURN a` in the same run. The check wants an index seek instead of the label scan."
                    ),
                    starter="PROFILE MATCH (a:Application {product: 'auto', status: 'declined'}) RETURN a",
                    hints=(
                        "CREATE INDEX <name> IF NOT EXISTS FOR (a:Application) ON (a.status)",
                        "Separate the two statements with ;",
                        "The console waits for the new index to come online before the PROFILE.",
                    ),
                    solution=(
                        "CREATE INDEX app_status IF NOT EXISTS FOR (a:Application) ON (a.status);\n"
                        "PROFILE MATCH (a:Application {product: 'auto', status: 'declined'}) RETURN a"
                    ),
                    check=Custom(check_index_seek, setup="DROP INDEX app_status IF EXISTS"),
                    wrong=(
                        "PROFILE MATCH (a:Application {product: 'auto', status: 'declined'}) RETURN a",
                        "CREATE INDEX app_status IF NOT EXISTS FOR (p:Person) ON (p.status);\nPROFILE MATCH (a:Application {product: 'auto', status: 'declined'}) RETURN a",
                    ),
                    explain="Indexes cost writes and memory: create them for properties you filter on often.",
                ),
            ),
        ),
    ),
)
