"""Prepare each chapter's studio data, idempotently, with the labs' own loading code.

Every function starts from scratch (drop, then load the seeded generator's data), so the
numbers the learner sees match the guide's. The studio uses its own namespaces, so it
never disturbs a lab, a check or the capstone:

    MongoDB    database larkspur_studio
    Redis      logical database 5
    Cassandra  keyspaces larkspur_studio and larkspur_studio_rf3
    DynamoDB   table larkspur_studio
    Neo4j      the default database (Community has only one: shared with chapter 6's
               lab and check and with the capstone, which all reset it too)
    lake/      lake/studio/chNN/
"""

from __future__ import annotations

import time
from collections import Counter
from typing import Any

from nosqlde import clients, datagen, lake
from nosqlde.config import SETTINGS
from nosqlde.studio.lessons.model import PrepareResult

MONGO_DB = "larkspur_studio"
REDIS_DB = 5
KEYSPACE = "larkspur_studio"
KEYSPACE_RF3 = "larkspur_studio_rf3"
DYNAMO_TABLE = "larkspur_studio"
SESSIONS_TABLE = "larkspur_studio_sessions"
STUDIO_LAKE = SETTINGS.lake_dir / "studio"

_world: datagen.World | None = None


def world() -> datagen.World:
    """The guide's world (seed 42), generated once per server."""
    global _world
    if _world is None:
        _world = datagen.generate(seed=42)
    return _world


def _done(result: PrepareResult, start: float) -> PrepareResult:
    result.seconds = round(time.perf_counter() - start, 2)
    return result


# ---------------------------------------------------------------- chapter 2


def prepare_mongo() -> PrepareResult:
    from nosqlde.labs import ch02_mongodb as lab

    start = time.perf_counter()
    out = PrepareResult()
    client = clients.mongo()
    try:
        client.drop_database(MONGO_DB)
        db = client[MONGO_DB]
        w = world()
        final_docs = datagen.applications_as_of(w, w.as_of)
        lab.load(db.applications, final_docs)
        lab.load(db.borrowers, [{"_id": b["borrower_id"], **b} for b in w.borrowers])
        lab.load(db.applications_ref, lab.referenced(final_docs))
        lab.create_validated(db)
        out.lines.append(
            f"applications: {db.applications.count_documents({})} documents (borrower embedded); "
            f"borrowers: {db.borrowers.count_documents({})}; applications_ref: "
            f"{db.applications_ref.count_documents({})} (borrower referenced)"
        )
        out.lines.append("applications_validated: empty, with step 2.5's $jsonSchema validator")

        # Step 2.9: a copy as of 30 April, then May's changes applied to it.
        inc = db.applications_inc
        lab.load(inc, datagen.applications_as_of(w, lab.T1))
        inc.create_index("updated_at")
        first = inc.count_documents({})
        changes = inc.bulk_write(lab.changes_between(w, lab.T1, lab.T2))
        out.lines.append(
            f"applications_inc: {first} documents as of {lab.T1.date()}, then {changes.upserted_count} "
            f"inserted and {changes.modified_count} updated (May), index on updated_at"
        )

        # Step 2.10: the same changes, captured from a change stream into cdc_events.
        out.lines.append(_capture_changes(db, w, lab))

        # Steps 2.7 and 2.8: the flattened tables, conformed, as Parquet for DuckDB.
        tables = lab.flattened_tables(final_docs)
        written, _ = lab.write_lake(tables, STUDIO_LAKE / "ch02")
        out.lines.append(
            "lake/studio/ch02/: "
            + ", ".join(f"{name}.parquet ({rows} rows)" for name, rows in written.items())
        )
    finally:
        client.close()
    return _done(out, start)


def _capture_changes(db: Any, w: datagen.World, lab: Any) -> str:
    cs = db.applications_cdc
    lab.load(cs, datagen.applications_as_of(w, lab.T1)[:10])
    captured: list[dict[str, Any]] = []

    def keep(change: dict[str, Any], consumer: str) -> None:
        full = change.get("fullDocument")
        captured.append(
            {
                "_id": len(captured) + 1,
                "consumer": consumer,
                "operationType": change["operationType"],
                "documentKey": change["documentKey"],
                "fullDocument": {"status": full["status"]} if full else None,
                "clusterTime": change.get("clusterTime"),
            }
        )

    with cs.watch(full_document="updateLookup") as stream:
        cs.insert_one({"_id": "X1", "status": "submitted"})
        cs.insert_one({"_id": "X2", "status": "submitted"})
        cs.update_one({"_id": "X1"}, {"$set": {"status": "approved"}})
        cs.update_one({"_id": "X2"}, {"$set": {"status": "declined"}})
        cs.delete_one({"_id": "X2"})
        n = 0
        deadline = time.monotonic() + 10
        while n < 5 and time.monotonic() < deadline:
            change = stream.try_next()
            if change is not None:
                keep(change, "consumer 1")
                n += 1
        token = stream.resume_token
    cs.insert_one({"_id": "X3", "status": "submitted"})
    cs.update_one({"_id": "X1"}, {"$set": {"status": "funded"}})
    cs.delete_one({"_id": "X1"})
    with cs.watch(resume_after=token, full_document="updateLookup") as stream:
        n = 0
        deadline = time.monotonic() + 10
        while n < 3 and time.monotonic() < deadline:
            change = stream.try_next()
            if change is not None:
                keep(change, "consumer 2 (resumed)")
                n += 1
    db.cdc_events.drop()
    db.cdc_events.insert_many(captured)
    ops = Counter(c["operationType"] for c in captured)
    return (
        f"cdc_events: {len(captured)} change events read from a change stream ({dict(sorted(ops.items()))})"
    )


# ---------------------------------------------------------------- chapter 3


def prepare_redis() -> PrepareResult:
    from nosqlde.labs import ch03_redis as lab

    start = time.perf_counter()
    out = PrepareResult()
    r: Any = clients.redis_client(REDIS_DB)
    try:
        r.flushdb()
        # chapter 3 may have changed these; put the image's defaults back
        r.config_set("maxmemory-policy", "noeviction")
        w = world()
        lab.load_structures(r, w)
        lab.fill_stream(r, w.payments)
        keys = sorted(r.scan_iter("ch03:*"))
        out.lines.append(f"logical database {REDIS_DB}: {len(keys)} keys from step 3.1 and 3.8")
        out.lines.append(f"stream {lab.STREAM}: {r.xlen(lab.STREAM)} entries, consumer group {lab.GROUP}")
        out.lines.append("maxmemory-policy reset to noeviction (the image's default)")
    finally:
        r.close()
    return _done(out, start)


# ---------------------------------------------------------------- chapter 4


def prepare_cassandra() -> PrepareResult:
    from nosqlde.labs import ch04_cassandra as lab

    start = time.perf_counter()
    out = PrepareResult()
    s = clients.cassandra()
    try:
        s.execute(f"DROP KEYSPACE IF EXISTS {KEYSPACE}")
        s.execute(
            f"CREATE KEYSPACE {KEYSPACE} WITH replication = {{'class': 'SimpleStrategy', 'replication_factor': 1}}"
        )
        s.set_keyspace(KEYSPACE)
        n = lab.create_and_load(s, world().payments)
        out.lines.append(f"{KEYSPACE}: payments_by_loan, payments_by_day, payments_by_method ({n} rows each)")
        lab.make_work_queue(s)
        out.lines.append("work_queue: 2000 rows in one partition, 1500 of them deleted (tombstones)")
        s.execute("CREATE TABLE loan_status (loan_id text PRIMARY KEY, status text, version int)")
        s.execute("INSERT INTO loan_status (loan_id, status, version) VALUES ('L0000006', 'active', 1)")
        out.lines.append("loan_status: L0000006 active, version 1")
        s.execute(f"DROP KEYSPACE IF EXISTS {KEYSPACE_RF3}")
        s.execute(
            f"CREATE KEYSPACE {KEYSPACE_RF3} WITH replication = "
            "{'class': 'SimpleStrategy', 'replication_factor': 3}"
        )
        s.execute(f"CREATE TABLE {KEYSPACE_RF3}.t (k text PRIMARY KEY, v text)")
        out.lines.append(f"{KEYSPACE_RF3}: replication factor 3 on this one node, table t")
    finally:
        s.cluster.shutdown()
    return _done(out, start)


# ---------------------------------------------------------------- chapter 5


def prepare_dynamodb() -> PrepareResult:
    from nosqlde.labs import ch05_dynamodb as lab

    start = time.perf_counter()
    out = PrepareResult()
    client = clients.dynamodb_client()
    ddb = clients.dynamodb_resource()
    lab.create_table(client, DYNAMO_TABLE)
    items = lab.items_for(world())
    tbl = ddb.Table(DYNAMO_TABLE)
    with tbl.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)
    counts = Counter(i["type"] for i in items)
    out.lines.append(
        f"{DYNAMO_TABLE}: {len(items)} items ("
        + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        + "), GSI1 on GSI1PK/GSI1SK"
    )
    # Step 5.8's point: an expired item stays readable until TTL deletes it, so reads
    # must filter on the expiry. A separate table keeps the scan numbers above equal to
    # the guide's. Fixed epochs keep the answer deterministic: 1 January 2025 (expired)
    # and 1 January 2100.
    lab.create_table(client, SESSIONS_TABLE)
    sessions = ddb.Table(SESSIONS_TABLE)
    for n, expires_at in ((1, 1_735_689_600), (2, 4_102_444_800), (3, 4_102_444_800)):
        sessions.put_item(Item={"PK": "SESSION#demo", "SK": f"TOKEN#{n}", "expires_at": expires_at})
    out.lines.append(
        f"{SESSIONS_TABLE}: 3 session tokens for SESSION#demo, one of them expired (TTL not enabled)"
    )
    return _done(out, start)


# ---------------------------------------------------------------- chapter 6


def prepare_neo4j() -> PrepareResult:
    from nosqlde.labs import ch06_neo4j as lab

    start = time.perf_counter()
    out = PrepareResult()
    driver = clients.neo4j()
    try:
        rows = lab.identity_rows(world())
        lab.reset(driver)
        driver.execute_query("DROP INDEX app_status IF EXISTS")
        lab.load(driver, rows)
        labels = driver.execute_query(
            "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY label"
        ).records
        out.lines.append("nodes: " + ", ".join(f"{r['label']} {r['n']}" for r in labels))
        edges = [dict(r) for r in driver.execute_query(lab.EDGES).records]
        n = lake.write_parquet(
            edges, STUDIO_LAKE / "ch06" / "edges.parquet", lake.arrow_schema(lab.EDGE_SCHEMA)
        )
        out.lines.append(f"lake/studio/ch06/edges.parquet: {n} identity edges, for the SQL comparison")
    finally:
        driver.close()
    return _done(out, start)
