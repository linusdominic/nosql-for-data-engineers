"""Build docs/explorer/data.js, the data behind the interactive explorer.

Run with:

    uv run --python 3.12 python tools/build_explorer_data.py

Two kinds of data end up in the file:

* Sample records, computed here from the same deterministic generator the labs use
  (`datagen.generate(seed=42)`): one funded application (A0000006, the guide's running
  example) in each database's shape, the fraud ring around A0000030 from chapter 6,
  the real partition sizes of chapter 4's three tables, the item sizes behind chapter 5's
  capacity numbers, and the watermark windows of chapter 2's step 2.9.
* Recorded lab output (`RECORDED`): numbers measured by `make lab-NN` and `make capstone`
  that need a database to reproduce. Each entry names its chapter and quotes the exact
  line of the guide it comes from; `tests/unit/test_explorer_data.py` checks that every
  quoted line and value is still in the guide, so the explorer cannot drift from it.

Where the generator can recompute a recorded number (row counts, partition sizes, the
watermark run sizes), this script asserts that both agree before writing anything.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from nosqlde import datagen
from nosqlde.labs.ch05_dynamodb import items_for
from nosqlde.labs.ch06_neo4j import identity_rows

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "guide"
OUT = ROOT / "docs" / "explorer" / "data.js"
REPO = "https://github.com/linusdominic/nosql-for-data-engineers"

SAMPLE_APP = "A0000006"
RING_START = "A0000030"
RING_TARGET = "A0001525"

CH = {
    0: "00-setup.md",
    1: "01-why-nosql.md",
    2: "02-document-stores-mongodb.md",
    3: "03-key-value-redis.md",
    4: "04-wide-column-cassandra.md",
    5: "05-dynamodb.md",
    6: "06-graph-neo4j.md",
    7: "07-capstone.md",
    8: "08-choosing-a-nosql-database.md",
}

# Headings the explorer links to: (chapter, heading text exactly as in the guide).
LINKS: dict[str, tuple[int, str]] = {
    "setup": (0, "0. Setup and how to use this guide"),
    "data": (0, "The data: Larkspur Lending (fictional)"),
    "families": (1, "The families"),
    "documents": (2, "Documents versus rows"),
    "indexes": (2, "Indexes and `explain()`"),
    "watermark": (2, "Full versus incremental extraction with a watermark"),
    "changestreams": (2, "Change data capture with change streams and resume tokens"),
    "redis_structures": (3, "Data structures, mapped to SQL"),
    "streams": (3, "Redis Streams with consumer groups as a lightweight queue"),
    "cassandra_model": (4, "Query-first modeling"),
    "allow_filtering": (4, "Why `ALLOW FILTERING` is a trap"),
    "hot_partitions": (4, "Hot partitions and time bucketing"),
    "consistency": (4, "Consistency levels"),
    "single_table": (5, "Single-table design"),
    "gsi": (5, "Global secondary indexes"),
    "scan": (5, "Scan with a filter reads everything"),
    "cypher": (6, "Cypher patterns versus SQL joins"),
    "rings": (6, "A lending use case: fraud rings"),
    "capstone": (7, "The systems and the pipeline"),
    "reconciliation": (7, "Reconciliation"),
    "model": (7, "The model"),
    "decision": (8, "A decision guide"),
    "comparison": (8, "Comparison"),
}


def rec(rid: str, chapter: int, step: str, label: str, context: str, **values: str) -> dict[str, Any]:
    """One recorded lab result: `context` is a verbatim fragment of the guide."""
    return {
        "id": rid,
        "chapter": CH[chapter],
        "step": step,
        "label": label,
        "context": context,
        "values": values,
    }


# Every measured number the explorer shows. Contexts are copied from the guide, which
# quotes the lab output; the run logs of 19 November 2026 print the same lines.
RECORDED: list[dict[str, Any]] = [
    rec("datagen_applications", 0, "make datagen", "Applications generated",
        "applications                  2393", value="2393"),
    rec("datagen_payments", 0, "make datagen", "Payment events generated",
        "payment_events               11465", value="11465"),
    rec("datagen_loans", 0, "make datagen", "Funded loans",
        "funded_loans                  1478", value="1478"),
    rec("datagen_rings", 0, "make datagen", "Planted fraud rings",
        "fraud_rings                      8", value="8"),
    # chapter 2
    rec("explain_docs", 2, "2.3", "Documents examined: no index vs compound index",
        "totalDocsExamined          2393              117", collscan="2393", ixscan="117"),
    rec("explain_keys", 2, "2.3", "Index keys examined",
        "totalKeysExamined          0                 117", collscan="0", ixscan="117"),
    rec("explain_returned", 2, "2.3", "Documents returned",
        "nReturned                  117               117", collscan="117", ixscan="117"),
    rec("explain_stages", 2, "2.3", "Plan stages",
        "stages                     SORT <- COLLSCAN  FETCH <- IXSCAN",
        collscan="SORT <- COLLSCAN", ixscan="FETCH <- IXSCAN"),
    rec("wm_run1", 2, "2.9", "Run 1, full extract",
        "run 1 (full):        1558 documents, watermark = 2025-04-30T23:01:15+00:00",
        docs="1558", watermark="2025-04-30T23:01:15+00:00"),
    rec("wm_changes", 2, "2.9", "Source changes in May",
        "source changes between runs: 438 inserted, 72 updated", inserted="438", updated="72"),
    rec("wm_run2", 2, "2.9", "Run 2, incremental",
        "run 2 (incremental): 510 documents, watermark = 2025-05-31T23:51:00+00:00",
        docs="510", watermark="2025-05-31T23:51:00+00:00"),
    rec("wm_run3", 2, "2.9", "Run 3, no changes", "run 3 (no changes):  0 documents", docs="0"),
    rec("wm_run4", 2, "2.9", "Run 4, after three hard deletes",
        "hard-deleted ['A0001418', 'A0001497', 'A0001456']; run 4 sees 0 documents",
        deleted="['A0001418', 'A0001497', 'A0001456']", docs="0"),
    rec("cs_consumer1", 2, "2.10", "Change stream, consumer 1",
        "consumer 1 read 5 events, saved the resume token, and stopped:", events="5"),
    rec("cs_c1_1", 2, "2.10", "Consumer 1, event 1", "insert  _id=X1", op="insert", id="X1"),
    rec("cs_c1_2", 2, "2.10", "Consumer 1, event 2", "insert  _id=X2", op="insert", id="X2"),
    rec("cs_c1_3", 2, "2.10", "Consumer 1, event 3", "update  _id=X1", op="update", id="X1"),
    rec("cs_c1_4", 2, "2.10", "Consumer 1, event 4", "update  _id=X2", op="update", id="X2"),
    rec("cs_c1_5", 2, "2.10", "Consumer 1, event 5", "delete  _id=X2", op="delete", id="X2"),
    rec("cs_down", 2, "2.10", "Changes while no consumer runs",
        "3 more changes happen while no consumer is running", events="3"),
    rec("cs_resumed_insert", 2, "2.10", "Resumed event 1",
        "insert  _id=X3  fullDocument={'status': 'submitted'}", op="insert", id="X3"),
    rec("cs_resumed_update", 2, "2.10", "Resumed event 2",
        "update  _id=X1  fullDocument=None", op="update", id="X1", full="None"),
    rec("cs_resumed_delete", 2, "2.10", "Resumed event 3", "delete  _id=X1", op="delete", id="X1"),
    # chapter 3
    rec("st_xadd", 3, "3.8", "Entries added", "XADD 21 entries to ch03:payments", entries="21"),
    rec("st_crash", 3, "3.8", "worker-a reads and crashes",
        "worker-a read 5 entries and crashed before XACK", read="5"),
    rec("st_pending", 3, "3.8", "After worker-b",
        "acknowledged 15; XPENDING -> 6 pending", acked="15", pending="6"),
    rec("st_consumers", 3, "3.8", "Pending per consumer",
        "{'name': 'worker-a', 'pending': 5}, {'name': 'worker-b', 'pending': 1}",
        worker_a="5", worker_b="1"),
    rec("st_claim", 3, "3.8", "XAUTOCLAIM", "after 1.1s idle, worker-b XAUTOCLAIMed 6 entries",
        idle="1.1s", claimed="6"),
    rec("st_delivered", 3, "3.8", "Delivery count after the claim",
        "1795094114907-0  worker-b   2", times_delivered="2"),
    rec("st_dead", 3, "3.8", "Poison message",
        "the poison entry was retried to 3 deliveries and moved to ch03:payments:dead_letter (1 entry). XPENDING -> 0",
        deliveries="3", dead_letter="1", pending="0"),
    rec("st_groups", 3, "3.8", "XINFO GROUPS", "entries-read=21, lag=0, pending=0",
        entries_read="21", lag="0", pending="0"),
    # chapter 4
    rec("cs_latest", 4, "4.2", "Latest payment of L0000006",
        "2025-12-13 19:55:53  11             65,781", event_time="2025-12-13 19:55:53",
        instalment="11", amount="65,781"),
    rec("af_key", 4, "4.3", "Query by partition key",
        "Read 11 live rows and 0 tombstone cells", read="11"),
    rec("af_filter", 4, "4.3", "ALLOW FILTERING: rows returned",
        "WHERE amount_cents > 215000 ALLOW FILTERING  75", returned="75"),
    rec("af_filter_read", 4, "4.3", "ALLOW FILTERING: rows read",
        "Read 11465 live rows and 0 tombstone cells;", read="11465"),
    rec("hp_method", 4, "4.4", "payments_by_method",
        "payments_by_method  method         3           6864             60%",
        partitions="3", largest="6864", share="60%"),
    rec("hp_day", 4, "4.4", "payments_by_day",
        "payments_by_day     event_day      332         68               0.6%",
        partitions="332", largest="68", share="0.6%"),
    rec("hp_loan", 4, "4.4", "payments_by_loan",
        "payments_by_loan    loan_id        1465        11               0.10%",
        partitions="1465", largest="11", share="0.10%"),
    rec("cl_rf1_one", 4, "4.6", "RF=1, ONE", "RF=1      ONE                ok", result="ok"),
    rec("cl_rf1_quorum", 4, "4.6", "RF=1, QUORUM", "RF=1      QUORUM             ok", result="ok"),
    rec("cl_rf1_all", 4, "4.6", "RF=1, ALL", "RF=1      ALL                ok", result="ok"),
    rec("cl_rf3_one", 4, "4.6", "RF=3, ONE", "RF=3      ONE                ok", result="ok"),
    rec("cl_rf3_quorum", 4, "4.6", "RF=3, QUORUM",
        "RF=3      QUORUM             Unavailable: needs 2 replicas, 1 alive",
        result="Unavailable: needs 2 replicas, 1 alive"),
    rec("cl_rf3_all", 4, "4.6", "RF=3, ALL",
        "RF=3      ALL                Unavailable: needs 3 replicas, 1 alive",
        result="Unavailable: needs 3 replicas, 1 alive"),
    # chapter 5
    rec("dd_items", 5, "5.2", "Items in the single table",
        "BatchWriteItem: 18814 items", items="18814"),
    rec("dd_ap1", 5, "5.3", "AP1 GetItem", "AP1 GetItem                         1      -             0.5",
        count="1", rcu="0.5"),
    rec("dd_ap2", 5, "5.3", "AP2 Query",
        "AP2 Query PK=BORROWER#B001532       5      5             0.5", count="5", rcu="0.5"),
    rec("dd_ap3", 5, "5.3", "AP3 Query",
        "AP3 Query LOAN#L0000006 Mar-Jun     4      4             0.5", count="4", rcu="0.5"),
    rec("dd_gsi", 5, "5.3", "AP4 Query on GSI1",
        "AP4 Query GSI1 declined since June  117    117           2.5",
        count="117", scanned="117", rcu="2.5"),
    rec("dd_scan", 5, "5.4", "Scan with a filter",
        "Scan + FilterExpression: 3 pages (1 MB each at most), ScannedCount=18814, Count=117, ConsumedCapacity=305.0 RCU",
        pages="3", scanned="18814", count="117", rcu="305.0"),
    # chapter 6
    rec("gr_reachable", 6, "6.4", "Reachable from A0000030",
        "applications reachable from A0000030 through shared phones, devices or addresses: ['A0000030', 'A0000185', 'A0000302', 'A0000413', 'A0001199', 'A0001493', 'A0001525', 'A0002134']",
        ids="['A0000030', 'A0000185', 'A0000302', 'A0000413', 'A0001199', 'A0001493', 'A0001525', 'A0002134']"),
    rec("gr_planted", 6, "6.4", "Planted ring",
        "planted ring (ground truth from the generator): ['A0000030', 'A0000302', 'A0000413', 'A0001199', 'A0001525']",
        ids="['A0000030', 'A0000302', 'A0000413', 'A0001199', 'A0001525']"),
    rec("gr_extra_185", 6, "6.4", "Why A0000185 is reached",
        "A0000185 is not in the planted ring: borrower B001204 also submitted a ring application",
        id="A0000185", borrower="B001204"),
    rec("gr_extra_1493", 6, "6.4", "Why A0001493 is reached",
        "A0001493 is not in the planted ring: borrower B001037 is linked through a ring member",
        id="A0001493", borrower="B001037"),
    rec("gr_extra_2134", 6, "6.4", "Why A0002134 is reached",
        "A0002134 is not in the planted ring: borrower B001829 also submitted a ring application",
        id="A0002134", borrower="B001829"),
    rec("gr_path", 6, "6.5", "Shortest path",
        "A0000030 to A0001525: 6 relationships", hops="6"),
    rec("gr_path_nodes", 6, "6.5", "Shortest path, nodes",
        "A0000030 - Device - A0000302 - Address - A0000413 - Phone - A0001525",
        path="A0000030 - Device - A0000302 - Address - A0000413 - Phone - A0001525"),
    rec("gr_flagged", 6, "6.7", "Flagged applications",
        "flagged applications: 45 = 32 planted + 13 extra", flagged="45", planted="32", extra="13"),
    # chapter 7
    rec("cp_before1", 7, "ingest", "Source changes before run 1",
        "before run 1  2025-06-20  2251      0             0            3085               200          94            2791",
        apps_new="2251", deliveries="3085", redelivered="200", dups="94", written="2791"),
    rec("cp_before2", 7, "ingest", "Source changes before run 2",
        "before run 2  2025-12-31  142       75            3            9145               200          273           8672",
        apps_new="142", apps_changed="75", erased="3", deliveries="9145", redelivered="200",
        dups="273", written="8672"),
    rec("cp_run1", 7, "runs", "Run 1, initial",
        "run 1 initial      2251        0              2025-01-01..2025-06-20  138         2791          6753",
        mongo="2251", deletes="0", days="2025-01-01..2025-06-20", partitions="138",
        payments="2791", edges="6753"),
    rec("cp_run2", 7, "runs", "Run 2, incremental",
        "run 2 incremental  217         3              2025-06-17..2025-12-31  198         8814          7170",
        mongo="217", deletes="3", days="2025-06-17..2025-12-31", partitions="198",
        payments="8814", edges="7170"),
    rec("cp_run3", 7, "runs", "Run 3, re-run",
        "run 3 re-run       0           0              2025-12-28..2025-12-31  4           111           7170",
        mongo="0", deletes="0", days="2025-12-28..2025-12-31", partitions="4",
        payments="111", edges="7170"),
    rec("cp_raw_mongo", 7, "runs", "Raw Mongo layer, before and after the re-run",
        "raw mongo application rows: before 2468 rows, checksum e82c607f38bb629e | after 2468 rows, checksum e82c607f38bb629e | unchanged",
        rows="2468", checksum="e82c607f38bb629e"),
    rec("cp_raw_cass", 7, "runs", "Raw Cassandra layer, before and after the re-run",
        "raw cassandra payment rows: before 11463 rows, checksum 4475019d3f9b667b | after 11463 rows, checksum 4475019d3f9b667b | unchanged",
        rows="11463", checksum="4475019d3f9b667b"),
    rec("cp_backfill", 7, "runs", "March backfill",
        "rewrote 31 day partitions (410 rows)", partitions="31", rows="410"),
    rec("cp_drift", 7, "extract", "Run 1 drift report",
        "coerced     requested_amount from string: 174", coerced="174"),
    rec("cp_erased", 7, "extract", "Erasures found by the key scan",
        "erased in the source: ['A0000004', 'A0000048', 'A0000052']; detected by the key scan: 3",
        ids="['A0000004', 'A0000048', 'A0000052']", detected="3"),
    rec("cp_late", 7, "extract", "Late events picked up by the lookback",
        "late events (paid before 2025-06-20, arrived after run 1): 2", late="2"),
    rec("rc_apps", 7, "reconcile", "mongo applications (id, status, updated_at)",
        "OK   mongo applications (id, status, updated_at) source    2390  lake    2390  checksum match",
        source="2390", lake="2390"),
    rec("rc_loans", 7, "reconcile", "mongo loans (id, principal, rate)",
        "OK   mongo loans (id, principal, rate)          source    1478  lake    1478  checksum match",
        source="1478", lake="1478"),
    rec("rc_events", 7, "reconcile", "cassandra payment events",
        "OK   cassandra payment events                   source   11463  lake   11463  checksum match",
        source="11463", lake="11463"),
    rec("rc_counters", 7, "reconcile", "cassandra daily counters vs lake sums",
        "OK   cassandra daily counters vs lake sums      source     332  lake     332  checksum match",
        source="332", lake="332"),
    rec("rc_edges", 7, "reconcile", "neo4j identity edges",
        "OK   neo4j identity edges                       source    7170  lake    7170  checksum match",
        source="7170", lake="7170"),
    rec("rc_dedup", 7, "reconcile", "redis dedup keys vs lake events (count)",
        "OK   redis dedup keys vs lake events (count)    source   11463  lake   11463  checksum match",
        source="11463", lake="11463"),
    rec("rc_summary", 7, "reconcile", "Reconciliation summary",
        "reconciliation: 6/6 OK; re-run and backfill idempotent: True", ok="6/6", idempotent="True"),
    rec("dpd_current", 7, "model", "current", "current     1319   0.00", loans="1319", arrears="0.00"),
    rec("dpd_1_29", 7, "model", "1-29", "1-29        49     31334.76", loans="49", arrears="31334.76"),
    rec("dpd_30_59", 7, "model", "30-59", "30-59       12     18828.80", loans="12", arrears="18828.80"),
    rec("dpd_60_89", 7, "model", "60-89", "60-89       14     32255.88", loans="14", arrears="32255.88"),
    rec("dpd_90", 7, "model", "90+", "90+         84     307007.79", loans="84", arrears="307007.79"),
    rec("ring_false", 7, "model", "Not ring-flagged", "False      1441   0.0541", loans="1441", share="0.0541"),
    rec("ring_true", 7, "model", "Ring-flagged", "True       37     0.8649", loans="37", share="0.8649"),
    rec("cp_lake", 7, "lake", "Lake size", "340 Parquet files, 4.6 MB", files="340", size="4.6 MB"),
]  # fmt: skip


def slug(heading: str) -> str:
    """GitHub's heading anchor: lower case, punctuation dropped, spaces to hyphens."""
    s = heading.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def guide_links() -> dict[str, str]:
    out: dict[str, str] = {}
    for key, (chapter, heading) in LINKS.items():
        text = (GUIDE / CH[chapter]).read_text()
        if not re.search(rf"^#+ {re.escape(heading)}$", text, flags=re.MULTILINE):
            raise SystemExit(f"heading not found in {CH[chapter]}: {heading!r}")
        anchor = "" if heading.startswith(f"{chapter}. ") else f"#{slug(heading)}"
        out[key] = f"{REPO}/blob/main/guide/{CH[chapter]}{anchor}"
    out["repo"] = REPO
    for chapter, name in CH.items():
        out[f"ch{chapter}"] = f"{REPO}/blob/main/guide/{name}"
    return out


def plain(value: Any) -> Any:
    """JSON-safe copy: datetimes as ISO strings, Decimals as floats."""
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [plain(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def recorded_value(rid: str, name: str = "value") -> str:
    for r in RECORDED:
        if r["id"] == rid:
            return str(r["values"][name])
    raise KeyError(rid)


def check(label: str, computed: Any, recorded: Any) -> None:
    if str(computed) != str(recorded):
        raise SystemExit(f"{label}: generator gives {computed!r}, the guide records {recorded!r}")


# ---------------------------------------------------------------------- the shapes


def sql_shape(doc: dict[str, Any], payments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The application as rows in normalised tables (the seven of chapter 2, plus payments)."""
    b, loan, dec = doc["borrower"], doc["loan"], doc["decision"]
    app_id, bid = doc["application_id"], b["borrower_id"]
    emp = b.get("employment") or {}

    def t(name: str, keys: dict[str, str], rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {"name": name, "keys": keys, "columns": list(rows[0]) if rows else [], "rows": rows}

    return [
        t("borrowers", {"borrower_id": "PK"},
          [{"borrower_id": bid, "full_name": b["full_name"], "date_of_birth": b["date_of_birth"],
            "annual_income": b["annual_income"]}]),
        t("employment", {"borrower_id": "FK"},
          [{"borrower_id": bid, "status": emp.get("status"), "employer": emp.get("employer"),
            "years": emp.get("years")}]),
        t("applications", {"application_id": "PK", "borrower_id": "FK"},
          [{"application_id": app_id, "borrower_id": bid, "product": doc["product"],
            "requested_amount": doc["requested_amount"], "term_months": doc["term_months"],
            "channel": doc["channel"], "status": doc["status"],
            "submitted_at": doc["submitted_at"], "updated_at": doc["updated_at"]}]),
        t("documents", {"application_id": "FK"},
          [{"application_id": app_id, "position": i, "doc_type": d["doc_type"],
            "uploaded_at": d["uploaded_at"], "verified": d["verified"]}
           for i, d in enumerate(doc["documents"])]),
        t("decisions", {"application_id": "PK, FK"},
          [{"application_id": app_id, "score": dec["score"], "outcome": dec["outcome"],
            "decided_at": dec["decided_at"]}]),
        {"name": "decline_reasons", "keys": {"application_id": "FK"},
         "columns": ["application_id", "position", "reason"], "rows": []},
        t("loans", {"loan_id": "PK", "application_id": "FK"},
          [{"loan_id": loan["loan_id"], "application_id": app_id, "principal": loan["principal"],
            "annual_rate": loan["annual_rate"], "term_months": loan["term_months"],
            "instalment": loan["instalment"], "originated_at": loan["originated_at"]}]),
        t("payments", {"event_id": "PK", "loan_id": "FK"},
          [{"event_id": p["event_id"], "loan_id": p["loan_id"], "instalment_no": p["instalment_no"],
            "event_time": p["event_time"], "amount_cents": p["amount_cents"], "method": p["method"]}
           for p in payments]),
    ]  # fmt: skip


def redis_shape(
    doc: dict[str, Any], payments: list[dict[str, Any]], borrower: dict[str, Any]
) -> list[dict[str, Any]]:
    """Keys a Redis instance would hold for this application, named as in chapters 3 and 7."""
    loan = doc["loan"]
    last = payments[-1]
    return [
        {"key": f"ch03:loan:{loan['loan_id']}:status", "type": "string", "ttl": -1,
         "value": "funded", "command": f"GET ch03:loan:{loan['loan_id']}:status"},
        {"key": f"ch03:borrower:{borrower['borrower_id']}", "type": "hash", "ttl": -1,
         "value": {"full_name": borrower["full_name"], "town": borrower["address"]["town"],
                   "income": str(borrower["annual_income"])},
         "command": f"HGETALL ch03:borrower:{borrower['borrower_id']}"},
        {"key": "ch03:scores", "type": "sorted set", "ttl": -1,
         "value": [[doc["application_id"], doc["decision"]["score"]]],
         "command": f"ZSCORE ch03:scores {doc['application_id']}"},
        {"key": "ops:payments:incoming", "type": "stream", "ttl": -1,
         "value": [{"event_id": p["event_id"], "loan_id": p["loan_id"],
                    "amount_cents": str(p["amount_cents"])} for p in payments[-3:]],
         "command": "XREADGROUP GROUP cassandra-ingest worker-2 COUNT 100 STREAMS ops:payments:incoming >"},
        {"key": f"ops:dedup:{last['event_id']}", "type": "string", "ttl": 30 * 86_400,
         "value": "1", "command": f"SET ops:dedup:{last['event_id']} 1 NX EX 2592000"},
    ]  # fmt: skip


def cassandra_shape(world: datagen.World, payments: list[dict[str, Any]]) -> dict[str, Any]:
    cols = ["loan_id", "event_time", "event_id", "event_day", "instalment_no", "amount_cents", "method"]

    def row(p: dict[str, Any]) -> dict[str, Any]:
        return {c: p[c] for c in cols}

    by_loan = [row(p) for p in sorted(payments, key=lambda p: p["event_time"], reverse=True)]
    latest = payments[-1]
    day_rows = sorted(
        (p for p in world.payments if p["event_day"] == latest["event_day"]),
        key=lambda p: (p["event_time"], p["event_id"]),
    )
    return {
        "by_loan": {"table": "payments_by_loan", "partition_key": ["loan_id"],
                    "clustering": ["event_time DESC", "event_id ASC"],
                    "partition": latest["loan_id"], "rows": by_loan},
        "by_day": {"table": "payments_by_day", "partition_key": ["event_day"],
                   "clustering": ["event_time DESC", "event_id ASC"],
                   "partition": latest["event_day"], "highlight": latest["event_id"],
                   "rows_total": len(day_rows), "rows": [row(p) for p in reversed(day_rows)]},
        "columns": cols,
    }  # fmt: skip


def dynamo_item_size(item: dict[str, Any]) -> int:
    """Approximate item size by DynamoDB's documented rules: attribute names plus values;
    a number takes about one byte per two significant digits plus one."""
    size = 0
    for name, value in item.items():
        size += len(name.encode())
        if isinstance(value, str):
            size += len(value.encode())
        elif isinstance(value, int | float | Decimal):
            digits = str(value).replace("-", "").replace(".", "").strip("0") or "0"
            size += math.ceil(len(digits) / 2) + 1
    return size


def dynamo(world: datagen.World, doc: dict[str, Any]) -> dict[str, Any]:
    items = items_for(world)
    check("single-table items", len(items), recorded_value("dd_items", "items"))
    bid, lid = doc["borrower"]["borrower_id"], doc["loan"]["loan_id"]
    shown = [i for i in items if i["PK"] in (f"BORROWER#{bid}", f"LOAN#{lid}")]
    check("AP2 items", sum(1 for i in shown if i["PK"] == f"BORROWER#{bid}"),
          recorded_value("dd_ap2", "count"))  # fmt: skip
    sizes = [dynamo_item_size(i) for i in items]
    matches = [
        dynamo_item_size(i)
        for i in items
        if i.get("GSI1PK") == "STATUS#declined" and i["GSI1SK"] >= "2025-06-01"
    ]
    check("declined since June", len(matches), recorded_value("dd_gsi", "count"))
    # Scan pages hold at most 1 MB; capacity is rounded up to 4 KB per page.
    pages: list[int] = [0]
    for s in sizes:
        if pages[-1] + s > 1_048_576:
            pages.append(0)
        pages[-1] += s
    check("scan pages", len(pages), recorded_value("dd_scan", "pages"))
    return {
        "items": [plain(i) for i in shown],
        "sizes": {
            "table_items": len(items),
            "table_bytes": sum(sizes),
            "match_items": len(matches),
            "match_bytes": sum(matches),
            "page_bytes": pages,
            "scan_rcu_estimate": sum(math.ceil(p / 4096) for p in pages) / 2,
            "gsi_rcu_estimate": math.ceil(sum(matches) / 4096) / 2,
        },
    }


# ---------------------------------------------------------------------- graph


def graph(world: datagen.World) -> dict[str, Any]:
    rows = identity_rows(world)
    by_id = {r["application_id"]: r for r in rows}
    kinds = {"phone": "Phone", "device_id": "Device", "address_key": "Address"}
    users: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in rows:
        for k in kinds:
            users[(k, r[k])].append(r["application_id"])

    def component(start: str) -> list[str]:
        seen, todo = {start}, [start]
        while todo:
            a = todo.pop()
            for k in kinds:
                for b in users[(k, by_id[a][k])]:
                    if b not in seen:
                        seen.add(b)
                        todo.append(b)
        return sorted(seen)

    def shortest(start: str, goal: str) -> list[str]:
        """Breadth-first search over application - identifier - application hops."""
        prev: dict[str, str | None] = {start: None}
        todo = [start]
        while todo:
            nxt: list[str] = []
            for node in todo:
                if node.startswith("A"):
                    neighbours = [f"{k}|{by_id[node][k]}" for k in kinds]
                else:
                    k, v = node.split("|", 1)
                    neighbours = users[(k, v)]
                for n in neighbours:
                    if n not in prev:
                        prev[n] = node
                        nxt.append(n)
            todo = nxt
        path, cur = [], goal
        while cur is not None:
            path.append(cur)
            cur = prev[cur]
        return path[::-1]

    ring = next(r for r in world.rings if RING_START in r)

    def subgraph(apps: list[str], shared_only: bool) -> dict[str, Any]:
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        people: dict[str, str] = {}
        for a in apps:
            r = by_id[a]
            role = "ring" if a in ring else "app"
            nodes.append({"id": a, "label": "Application", "role": role, "status": r["status"],
                          "product": r["product"], "borrower_id": r["borrower_id"]})  # fmt: skip
            people[r["borrower_id"]] = r["name"]
            edges.append({"from": r["borrower_id"], "to": a, "type": "SUBMITTED"})
        for bid, name in sorted(people.items()):
            nodes.append({"id": bid, "label": "Person", "name": name})
        idents: dict[str, dict[str, Any]] = {}
        for a in apps:
            for k, label in kinds.items():
                value = by_id[a][k]
                sharers = [x for x in users[(k, value)] if x in apps]
                if shared_only and len(sharers) < 2:
                    continue
                nid = f"{k}|{value}"
                idents.setdefault(nid, {"id": nid, "label": label, "value": value})
                rel = {"phone": "USES_PHONE", "device_id": "USES_DEVICE", "address_key": "AT_ADDRESS"}[k]
                edges.append({"from": a, "to": nid, "type": rel, "shared": len(sharers) > 1})
        nodes.extend(idents.values())
        return {"nodes": nodes, "edges": edges}

    reach = component(RING_START)
    check("reachable from A0000030", reach, recorded_value("gr_reachable", "ids"))
    check("planted ring", ring, recorded_value("gr_planted", "ids"))
    path = shortest(RING_START, RING_TARGET)
    pretty = " - ".join(p if p.startswith("A") else kinds[p.split("|")[0]] for p in path)
    check("shortest path", pretty, recorded_value("gr_path_nodes", "path"))
    sample = component(SAMPLE_APP)
    return {
        "ring": {**subgraph(reach, shared_only=True), "start": RING_START, "planted": ring,
                 "path": path, "target": RING_TARGET},
        "sample": {**subgraph(sample, shared_only=False), "start": SAMPLE_APP},
    }  # fmt: skip


# ---------------------------------------------------------------------- chapter 4, 2


def partitions(world: datagen.World) -> dict[str, Any]:
    designs = {
        "method": ("payments_by_method", "((method), event_time, event_id)", lambda p: p["method"]),
        "method_month": (
            "payments_by_method_month",
            "((method, month), event_time, event_id)",
            lambda p: f"{p['method']}:{p['event_day'].strftime('%Y-%m')}",
        ),
        "event_day": (
            "payments_by_day",
            "((event_day), event_time, event_id)",
            lambda p: str(p["event_day"]),
        ),
        "loan_id": ("payments_by_loan", "((loan_id), event_time, event_id)", lambda p: p["loan_id"]),
    }
    out: dict[str, Any] = {"total_rows": len(world.payments), "designs": {}}
    for key, (table, pk, fn) in designs.items():
        counts = Counter(fn(p) for p in world.payments)
        out["designs"][key] = {
            "table": table,
            "primary_key": pk,
            "partitions": sorted(([k, v] for k, v in counts.items()), key=lambda kv: (-kv[1], kv[0])),
        }
    for key, rid in (("method", "hp_method"), ("event_day", "hp_day"), ("loan_id", "hp_loan")):
        parts = out["designs"][key]["partitions"]
        check(f"{key} partitions", len(parts), recorded_value(rid, "partitions"))
        check(f"{key} largest", parts[0][1], recorded_value(rid, "largest"))
    check("payment events", len(world.payments), recorded_value("datagen_payments"))
    return out


def watermark(world: datagen.World) -> dict[str, Any]:
    """Step 2.9 recomputed: the same snapshots, changes and windows as the lab."""
    t1 = datetime(2025, 4, 30, 23, 59, 59, tzinfo=UTC)
    t2 = datetime(2025, 5, 31, 23, 59, 59, tzinfo=UTC)
    first = sorted(datagen.applications_as_of(world, t1), key=lambda d: d["updated_at"])
    wm1 = first[-1]["updated_at"]
    inserted = updated = 0
    for d in datagen.applications_as_of(world, t2):
        old = datagen.application_as_of(world.applications[int(d["_id"][1:]) - 1], t1)
        if old is None:
            inserted += 1
        elif old["updated_at"] != d["updated_at"]:
            updated += 1
    second = sorted(
        (d for d in datagen.applications_as_of(world, t2) if d["updated_at"] > wm1),
        key=lambda d: d["updated_at"],
    )
    victims = [d["_id"] for d in second[:3]]
    check("run 1 documents", len(first), recorded_value("wm_run1", "docs"))
    check("run 1 watermark", wm1.isoformat(), recorded_value("wm_run1", "watermark"))
    check("inserted", inserted, recorded_value("wm_changes", "inserted"))
    check("updated", updated, recorded_value("wm_changes", "updated"))
    check("run 2 documents", len(second), recorded_value("wm_run2", "docs"))
    check("run 2 watermark", second[-1]["updated_at"].isoformat(), recorded_value("wm_run2", "watermark"))
    check("deleted", victims, recorded_value("wm_run4", "deleted"))
    # A few real documents for each window, to show what the extract reads.
    return {
        "t1": t1.isoformat(),
        "t2": t2.isoformat(),
        "sample_run1": [[d["_id"], d["status"], d["updated_at"].isoformat()] for d in first[-3:]],
        "sample_run2": [[d["_id"], d["status"], d["updated_at"].isoformat()] for d in second[:3]],
        "victims": victims,
    }


# ---------------------------------------------------------------------- main


def build() -> dict[str, Any]:
    world = datagen.generate(seed=42)
    summary = datagen.summary(world)
    check("applications", summary["applications"], recorded_value("datagen_applications"))
    check("funded loans", summary["funded_loans"], recorded_value("datagen_loans"))
    check("rings", summary["fraud_rings"], recorded_value("datagen_rings"))
    final = datagen.applications_as_of(world, world.as_of)
    doc = next(d for d in final if d["_id"] == SAMPLE_APP)
    loan_id = doc["loan"]["loan_id"]
    payments = [p for p in world.payments if p["loan_id"] == loan_id]
    borrower = next(b for b in world.borrowers if b["borrower_id"] == doc["borrower"]["borrower_id"])
    cass = cassandra_shape(world, payments)
    top = cass["by_loan"]["rows"][0]
    check("latest payment", top["event_time"].strftime("%Y-%m-%d %H:%M:%S"),
          recorded_value("cs_latest", "event_time"))  # fmt: skip
    check("latest amount", f"{top['amount_cents']:,}", recorded_value("cs_latest", "amount"))
    check("payments of L0000006", len(payments), recorded_value("af_key", "read"))
    return {
        "generated_by": "tools/build_explorer_data.py from nosqlde.datagen.generate(seed=42)",
        "links": guide_links(),
        "summary": summary,
        "sample": {
            "application_id": SAMPLE_APP,
            "loan_id": loan_id,
            "borrower_id": doc["borrower"]["borrower_id"],
            "document": plain(doc),
            "sql": plain(sql_shape(doc, payments)),
            "redis": plain(redis_shape(doc, payments, borrower)),
            "cassandra": plain(cass),
            "dynamodb": dynamo(world, doc),
        },
        "graph": graph(world),
        "partitions": partitions(world),
        "watermark": watermark(world),
        "recorded": RECORDED,
    }


def render(data: dict[str, Any]) -> str:
    body = json.dumps(data, indent=1, ensure_ascii=False, sort_keys=False)
    return (
        "// Generated by tools/build_explorer_data.py (make explorer-data). Do not edit by hand.\n"
        "// Sample records come from nosqlde.datagen.generate(seed=42); `recorded` holds lab\n"
        "// output quoted in the guide, each with its chapter and the exact guide line.\n"
        f"window.EXPLORER_DATA = {body};\n"
    )


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = render(build())
    OUT.write_text(text)
    print(
        f"wrote {OUT.relative_to(ROOT)} ({len(text.encode()) / 1024:.0f} KB, {len(RECORDED)} recorded results)"
    )


if __name__ == "__main__":
    main()
