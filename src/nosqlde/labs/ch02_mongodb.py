"""Chapter 2 lab: MongoDB as a document store, and getting data out of it.

Run with `make lab-02` (MongoDB must be up: `make up-02`). Every step prints what it
did, so the output can be read next to guide/02-document-stores-mongodb.md.
The lab drops and recreates the database `larkspur_ch02`, so it is safe to re-run.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from pymongo import ASCENDING, ReplaceOne
from pymongo.collection import Collection
from pymongo.errors import WriteError

from nosqlde import clients, datagen, drift, flatten, lake
from nosqlde.config import SETTINGS
from nosqlde.console import heading, say, show_json, step, table

DB = "larkspur_ch02"

# The target schema for the flattened `applications` table in the lake.
APPLICATION_SCHEMA: dict[str, str] = {
    "application_id": "string",
    "borrower__borrower_id": "string",
    "borrower__full_name": "string",
    "borrower__date_of_birth": "date",
    "borrower__annual_income": "int",
    "borrower__employment__status": "string",
    "borrower__employment__employer": "string",
    "borrower__employment__years": "int",
    "contact__email": "string",
    "contact__phone": "string",
    "address__line1": "string",
    "address__town": "string",
    "address__postcode": "string",
    "device_id": "string",
    "product": "string",
    "requested_amount": "decimal",
    "term_months": "int",
    "channel": "string",
    "submitted_at": "timestamp",
    "status": "string",
    "decision__score": "int",
    "decision__outcome": "string",
    "decision__decided_at": "timestamp",
    "updated_at": "timestamp",
    "schema_version": "int",
}
DOCUMENT_SCHEMA = {
    "application_id": "string",
    "position": "int",
    "doc_type": "string",
    "uploaded_at": "timestamp",
    "verified": "bool",
}
REASON_SCHEMA = {"application_id": "string", "position": "int", "reason": "string"}
LOAN_SCHEMA = {
    "loan_id": "string",
    "application_id": "string",
    "borrower_id": "string",
    "product": "string",
    "principal": "decimal",
    "annual_rate": "float",
    "term_months": "int",
    "instalment": "decimal",
    "originated_at": "timestamp",
}


def lab_dir() -> Path:
    return SETTINGS.lake_dir / "ch02"


def load(coll: Collection[dict[str, Any]], docs: list[dict[str, Any]]) -> None:
    coll.drop()
    if docs:
        coll.insert_many(docs, ordered=False)


def explain_summary(coll: Collection[dict[str, Any]], query: dict[str, Any], sort: Any) -> dict[str, Any]:
    """The few explain('executionStats') numbers that matter, pulled out of the tree."""
    plan = coll.find(query).sort(sort).explain()
    stats = plan["executionStats"]
    stages: list[str] = []
    node = plan["queryPlanner"]["winningPlan"]
    node = node.get("queryPlan", node)  # 8.0 nests the plan under queryPlan (SBE engine)
    while node:
        stages.append(node["stage"])
        node = node.get("inputStage")
    return {
        "stages": " <- ".join(stages),
        "nReturned": stats["nReturned"],
        "totalKeysExamined": stats["totalKeysExamined"],
        "totalDocsExamined": stats["totalDocsExamined"],
    }


def run() -> None:
    heading("Chapter 2 lab: MongoDB")
    client = clients.mongo()
    client.drop_database(DB)
    db = client[DB]
    world = datagen.generate(seed=42)
    final_docs = datagen.applications_as_of(world, world.as_of)
    out = lab_dir()

    # ------------------------------------------------------------------ 2.1
    step("2.1", "Insert documents")
    start = time.perf_counter()
    load(db.applications, final_docs)
    took = time.perf_counter() - start
    say(f"inserted {db.applications.count_documents({})} application documents in {took:.2f}s")
    sample = db.applications.find_one({"_id": "A0000006"})
    assert sample is not None
    sample["documents"] = sample["documents"][:1]
    say("one document (find_one({'_id': 'A0000006'})):")
    show_json(sample)

    # ------------------------------------------------------------------ 2.2
    step("2.2", "Embed versus reference")
    load(db.borrowers, [{"_id": b["borrower_id"], **b} for b in world.borrowers])
    referenced = []
    for d in final_docs:
        r = {k: v for k, v in d.items() if k != "borrower"}
        r["borrower_id"] = d["borrower"]["borrower_id"]
        referenced.append(r)
    load(db.applications_ref, referenced)
    sizes = {}
    for name in ("applications", "applications_ref"):
        agg = list(db[name].aggregate([{"$group": {"_id": None, "avg": {"$avg": {"$bsonSize": "$$ROOT"}}}}]))
        sizes[name] = round(agg[0]["avg"])
    say(f"average document size, borrower embedded:   {sizes['applications']} bytes")
    say(f"average document size, borrower referenced: {sizes['applications_ref']} bytes")
    joined = list(
        db.applications_ref.aggregate(
            [
                {"$match": {"_id": "A0000006"}},
                {
                    "$lookup": {
                        "from": "borrowers",
                        "localField": "borrower_id",
                        "foreignField": "_id",
                        "as": "borrower",
                    }
                },
                {"$project": {"_id": 1, "product": 1, "borrower.full_name": 1}},
            ]
        )
    )
    say("$lookup (a left outer join) from applications_ref to borrowers:")
    show_json(joined)

    # ------------------------------------------------------------------ 2.3
    step("2.3", "Indexes and explain()")
    query = {"status": "declined", "submitted_at": {"$gte": datetime(2025, 6, 1, tzinfo=UTC)}}
    sort = [("submitted_at", ASCENDING)]
    before = explain_summary(db.applications, query, sort)
    db.applications.create_index([("status", ASCENDING), ("submitted_at", ASCENDING)])
    after = explain_summary(db.applications, query, sort)
    table(
        [[k, before[k], after[k]] for k in before],
        ["explain('executionStats')", "no index", "index {status:1, submitted_at:1}"],
    )
    db.applications.create_index("documents.doc_type")
    plan = db.applications.find({"documents.doc_type": "payslip"}).explain()
    winning = plan["queryPlanner"]["winningPlan"]
    winning = winning.get("queryPlan", winning)
    ixscan = winning.get("inputStage", winning)
    say(
        f"index on the array field documents.doc_type: stage={ixscan['stage']}, "
        f"isMultiKey={ixscan.get('isMultiKey')}"
    )

    # ------------------------------------------------------------------ 2.4
    step("2.4", "The aggregation pipeline, stage by stage, next to SQL")
    pipeline: list[dict[str, Any]] = [
        {"$match": {"status": {"$ne": "submitted"}}},  # WHERE
        {
            "$group": {  # GROUP BY product
                "_id": "$product",
                "applications": {"$sum": 1},  # COUNT(*)
                "approved": {"$sum": {"$cond": [{"$in": ["$status", ["approved", "funded"]]}, 1, 0]}},
                "avg_score": {"$avg": "$decision.score"},  # AVG(...)
            }
        },
        {
            "$project": {  # SELECT expressions
                "applications": 1,
                "approved": 1,
                "approval_rate": {"$round": [{"$divide": ["$approved", "$applications"]}, 4]},
                "avg_score": {"$round": ["$avg_score", 1]},
            }
        },
        {"$sort": {"_id": 1}},  # ORDER BY
    ]
    mongo_rows = [
        [r["_id"], r["applications"], r["approved"], r["approval_rate"], r["avg_score"]]
        for r in db.applications.aggregate(pipeline)
    ]
    table(mongo_rows, ["product", "applications", "approved", "approval_rate", "avg_score"])
    unwind = list(
        db.applications.aggregate(
            [
                {"$unwind": "$documents"},  # one row per array element, like a join
                {"$match": {"documents.verified": False}},
                {"$group": {"_id": "$documents.doc_type", "unverified": {"$sum": 1}}},
                {"$sort": {"_id": 1}},
            ]
        )
    )
    say("$unwind documents, then count unverified uploads per type:")
    table([[r["_id"], r["unverified"]] for r in unwind], ["doc_type", "unverified"])

    # ------------------------------------------------------------------ 2.5
    step("2.5", "Schema validation with $jsonSchema")
    db.drop_collection("applications_validated")
    db.create_collection(
        "applications_validated",
        validator={
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["application_id", "requested_amount", "status"],
                "properties": {
                    "application_id": {"bsonType": "string"},
                    "requested_amount": {"bsonType": ["double", "int", "long", "decimal"]},
                    "status": {"enum": ["submitted", "approved", "declined", "withdrawn", "funded"]},
                },
            }
        },
        validationLevel="strict",
        validationAction="error",
    )
    good = next(d for d in final_docs if isinstance(d["requested_amount"], float))
    bad = next(d for d in final_docs if isinstance(d["requested_amount"], str))
    db.applications_validated.insert_one(dict(good))
    say(f"insert {good['_id']} (requested_amount={good['requested_amount']!r}): accepted")
    try:
        db.applications_validated.insert_one(dict(bad))
    except WriteError as err:
        details = (err.details or {}).get("errInfo", {}).get("details", {})
        rule = details.get("schemaRulesNotSatisfied", [{}])[0]
        say(
            f"insert {bad['_id']} (requested_amount={bad['requested_amount']!r}): rejected, "
            f"code {err.code}, '{(err.details or {}).get('errmsg')}', "
            f"operator {rule.get('operatorName')!r}"
        )

    # ------------------------------------------------------------------ 2.6
    step("2.6", "A multi-document transaction")
    db.drop_collection("loans")
    db.create_collection("loans")
    target = next(d for d in final_docs if d["status"] == "approved")
    db.applications.update_one({"_id": target["_id"]}, {"$set": {"status": "approved"}})

    def fund(session: Any, fail: bool) -> None:
        db.applications.update_one({"_id": target["_id"]}, {"$set": {"status": "funded"}}, session=session)
        if fail:
            raise RuntimeError("simulated crash between the two writes")
        db.loans.insert_one({"_id": "L-DEMO", "application_id": target["_id"]}, session=session)

    with client.start_session() as session:
        try:
            session.with_transaction(lambda s: fund(s, fail=True))
        except RuntimeError as err:
            say(f"transaction 1 raised '{err}' and was aborted")
    status = db.applications.find_one({"_id": target["_id"]}, {"status": 1})
    say(
        f"  after abort:  application status={status['status'] if status else None!r}, "
        f"loans={db.loans.count_documents({})}"
    )
    with client.start_session() as session:
        session.with_transaction(lambda s: fund(s, fail=False))
    status = db.applications.find_one({"_id": target["_id"]}, {"status": 1})
    say(
        f"  after commit: application status={status['status'] if status else None!r}, "
        f"loans={db.loans.count_documents({})}"
    )
    db.applications.update_one({"_id": target["_id"]}, {"$set": {"status": target["status"]}})

    # ------------------------------------------------------------------ 2.7
    step("2.7", "Flatten nested documents and arrays into tables")
    tables: dict[str, list[dict[str, Any]]] = {
        "applications": [],
        "application_documents": [],
        "decline_reasons": [],
        "loans": [],
    }
    for doc in db.applications.find({}).sort("_id", ASCENDING):
        for name, rows in flatten.flatten_application(doc).items():
            tables[name].extend(rows)
    table([[n, len(r)] for n, r in tables.items()], ["table", "rows"])
    say("columns of the flattened applications table (first 8):")
    say("  " + ", ".join(list(tables["applications"][0])[:8]))

    # ------------------------------------------------------------------ 2.8
    step("2.8", "Schema drift: find it, conform it, count it")
    inferred = drift.infer_schema(tables["applications"])
    drifting = {c: dict(t) for c, t in inferred.items() if len(t) > 1}
    say("columns with more than one type (column: {type: rows}):")
    for col, types in drifting.items():
        say(f"  {col}: {types}")
    missing_cols = [c for c in APPLICATION_SCHEMA if c not in inferred]
    say(f"schema columns never seen: {missing_cols or 'none'}")
    conformed, report = drift.conform(tables["applications"], APPLICATION_SCHEMA)
    say("drift report for applications:")
    for line in report.lines():
        say(f"  {line}")
    written = {
        "applications": lake.write_parquet(
            conformed, out / "applications.parquet", lake.arrow_schema(APPLICATION_SCHEMA, True)
        )
    }
    for name, schema in (
        ("application_documents", DOCUMENT_SCHEMA),
        ("decline_reasons", REASON_SCHEMA),
        ("loans", LOAN_SCHEMA),
    ):
        rows, _ = drift.conform(tables[name], schema, on_new="drop")
        written[name] = lake.write_parquet(rows, out / f"{name}.parquet", lake.arrow_schema(schema))
    say(f"wrote Parquet to {out}/: {written}")
    con = duckdb.connect()
    loan_rows = con.execute(
        f"""
        SELECT a.product,
               count(*)                         AS loans,
               sum(l.principal)                 AS principal,
               round(avg(l.annual_rate), 4)     AS avg_rate,
               count(*) FILTER (WHERE a._rescued IS NOT NULL) AS with_rescued_fields
        FROM '{out}/loans.parquet' l
        JOIN '{out}/applications.parquet' a USING (application_id)
        GROUP BY a.product ORDER BY a.product
        """
    ).fetchall()
    say("DuckDB over the Parquet files (loans joined to applications):")
    table(loan_rows, ["product", "loans", "principal", "avg_rate", "with_rescued_fields"])
    rescued_example = con.execute(
        f"SELECT _rescued FROM '{out}/applications.parquet' WHERE _rescued IS NOT NULL LIMIT 1"
    ).fetchone()
    say(f"example _rescued value: {rescued_example[0] if rescued_example else None}")
    amount_type = con.execute(
        f"SELECT typeof(requested_amount) FROM '{out}/applications.parquet' LIMIT 1"
    ).fetchone()
    say(f"requested_amount type in Parquet: {amount_type[0] if amount_type else None}")

    # ------------------------------------------------------------------ 2.9
    step("2.9", "Incremental extraction with an updated_at watermark")
    t1 = datetime(2025, 4, 30, 23, 59, 59, tzinfo=UTC)
    t2 = datetime(2025, 5, 31, 23, 59, 59, tzinfo=UTC)
    inc = db.applications_inc
    load(inc, datagen.applications_as_of(world, t1))
    inc.create_index("updated_at")
    first = list(inc.find({}, {"_id": 1, "updated_at": 1}).sort("updated_at", ASCENDING))
    watermark = first[-1]["updated_at"]
    say(f"run 1 (full):        {len(first)} documents, watermark = {watermark.isoformat()}")
    changes = [
        ReplaceOne({"_id": d["_id"]}, d, upsert=True)
        for d in datagen.applications_as_of(world, t2)
        if (old := datagen.application_as_of(world.applications[int(d["_id"][1:]) - 1], t1)) is None
        or old["updated_at"] != d["updated_at"]
    ]
    result = inc.bulk_write(changes)
    say(f"source changes between runs: {result.upserted_count} inserted, {result.modified_count} updated")
    second = list(inc.find({"updated_at": {"$gt": watermark}}).sort("updated_at", ASCENDING))
    watermark2 = second[-1]["updated_at"]
    say(f"run 2 (incremental): {len(second)} documents, watermark = {watermark2.isoformat()}")
    third = list(inc.find({"updated_at": {"$gt": watermark2}}))
    say(f"run 3 (no changes):  {len(third)} documents")
    victims = [d["_id"] for d in second[:3]]
    inc.delete_many({"_id": {"$in": victims}})
    fourth = list(inc.find({"updated_at": {"$gt": watermark2}}))
    say(f"hard-deleted {victims}; run 4 sees {len(fourth)} documents: a watermark query cannot see deletes")

    # ------------------------------------------------------------------ 2.10
    step("2.10", "Change streams and resuming from a resume token")
    cs = db.applications_cdc
    load(cs, datagen.applications_as_of(world, t1)[:10])
    token_file = out / "_state" / "resume_token.json"
    with cs.watch(full_document="updateLookup") as stream:
        cs.insert_one({"_id": "X1", "status": "submitted"})
        cs.insert_one({"_id": "X2", "status": "submitted"})
        cs.update_one({"_id": "X1"}, {"$set": {"status": "approved"}})
        cs.update_one({"_id": "X2"}, {"$set": {"status": "declined"}})
        cs.delete_one({"_id": "X2"})
        events: list[dict[str, Any]] = []
        while len(events) < 5:
            change = stream.try_next()
            if change is not None:
                events.append(change)
        lake.write_json(token_file, {"resume_token": stream.resume_token})
    say("consumer 1 read 5 events, saved the resume token, and stopped:")
    for e in events:
        say(f"  {e['operationType']:<7} _id={e['documentKey']['_id']}")
    # While the consumer is down, the application keeps writing.
    cs.insert_one({"_id": "X3", "status": "submitted"})
    cs.update_one({"_id": "X1"}, {"$set": {"status": "funded"}})
    cs.delete_one({"_id": "X1"})
    say("3 more changes happen while no consumer is running")
    saved = json.loads(token_file.read_text())["resume_token"]
    resumed: list[dict[str, Any]] = []
    with cs.watch(resume_after=saved, full_document="updateLookup") as stream:
        deadline = time.monotonic() + 10
        while len(resumed) < 3 and time.monotonic() < deadline:
            change = stream.try_next()
            if change is not None:
                resumed.append(change)
    say("consumer 2 started with resume_after=<saved token> and received:")
    for e in resumed:
        op = e["operationType"]
        full = e.get("fullDocument")
        lookup = "" if op == "delete" else f"  fullDocument={full and {'status': full['status']}}"
        say(f"  {op:<7} _id={e['documentKey']['_id']}{lookup}")
    say(f"\nlab files are in {out}/")
    client.close()
