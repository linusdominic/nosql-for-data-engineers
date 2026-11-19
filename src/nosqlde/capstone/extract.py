"""Extract each source into lake/capstone/raw, incrementally and re-runnably.

MongoDB  - updated_at watermark. The window is (previous watermark, source max at
           start of run], so the batch file name is fixed by the data, and a re-run
           of the same window overwrites the same file. A key-only scan finds
           hard deletes, which a watermark can never see.
Cassandra- read whole day partitions of payment_events_by_day, from a few days before
           the last extracted day (late events land in old days) up to as_of, and
           overwrite each day's file. A backfill is the same function with a range.
Neo4j    - small enough to snapshot: one file per as_of date, overwritten on re-run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from nosqlde import drift, flatten, lake
from nosqlde.capstone.sources import KEYSPACE, MONGO_DB, Sources

LOOKBACK_DAYS = 3
GO_LIVE = date(2025, 1, 1)  # the first day the servicing system could hold payments

APPLICATION_SCHEMA: dict[str, str] = {
    "application_id": "string",
    "borrower__borrower_id": "string",
    "borrower__annual_income": "int",
    "borrower__employment__status": "string",
    "product": "string",
    "channel": "string",
    "requested_amount": "decimal",
    "term_months": "int",
    "submitted_at": "timestamp",
    "status": "string",
    "decision__score": "int",
    "decision__decided_at": "timestamp",
    "marketing_consent": "bool",  # added to the schema after chapter 2 found it
    "loan__loan_id": "string",
    "loan__principal": "decimal",
    "loan__annual_rate": "float",
    "loan__term_months": "int",
    "loan__instalment": "decimal",
    "loan__originated_at": "timestamp",
    "updated_at": "timestamp",
    "schema_version": "int",
}
# Absent by design: no decision until decided, no loan until funded, and
# marketing_consent only exists on documents written since May 2025.
OPTIONAL = frozenset(
    [c for c in APPLICATION_SCHEMA if c.startswith(("loan__", "decision__"))] + ["marketing_consent"]
)
PROJECTION = {
    "application_id": 1, "borrower.borrower_id": 1, "borrower.annual_income": 1,
    "borrower.employment.status": 1, "product": 1, "channel": 1, "requested_amount": 1,
    "term_months": 1, "submitted_at": 1, "status": 1, "decision.score": 1,
    "decision.decided_at": 1, "marketing_consent": 1, "updated_at": 1, "schema_version": 1,
    "loan.loan_id": 1, "loan.principal": 1, "loan.annual_rate": 1, "loan.term_months": 1,
    "loan.instalment": 1, "loan.originated_at": 1,
}  # fmt: skip
PAYMENT_SCHEMA = {
    "event_id": "string",
    "loan_id": "string",
    "event_time": "timestamp",
    "event_day": "date",
    "ingested_at": "timestamp",
    "instalment_no": "int",
    "amount_cents": "int",
    "method": "string",
}
EDGE_SCHEMA = {"application_id": "string", "borrower_id": "string", "kind": "string", "value": "string"}
DELETED_SCHEMA = {"application_id": "string", "detected_at": "timestamp"}


def raw(root: Path, *parts: str) -> Path:
    return root.joinpath("raw", *parts)


def _stamp(t: datetime) -> str:
    return t.strftime("%Y%m%dT%H%M%S")


@dataclass
class MongoResult:
    window: tuple[datetime | None, datetime | None]
    rows: int
    deleted: int
    report: drift.DriftReport
    file: str | None


def extract_mongo(src: Sources, root: Path, state: lake.State, as_of: datetime) -> MongoResult:
    coll = src.mongo[MONGO_DB].applications
    wm_raw = state.get("mongo.applications.watermark")
    low = datetime.fromisoformat(wm_raw) if wm_raw else None
    top = coll.find_one({}, {"updated_at": 1}, sort=[("updated_at", -1)])
    high = top["updated_at"] if top else None
    report = drift.DriftReport()
    rows_written = 0
    file = None
    if high is not None and (low is None or high > low):
        query: dict[str, Any] = {"updated_at": {"$lte": high}}
        if low is not None:
            query["updated_at"]["$gt"] = low
        # Project only the fields the lake needs. Names, dates of birth and contact
        # details never leave the source: less to secure, less to erase later.
        docs = list(coll.find(query, PROJECTION).sort([("updated_at", 1), ("_id", 1)]))
        flat = [flatten.flatten_document(d, skip=frozenset({"_id"})) for d in docs]
        conformed, report = drift.conform(flat, APPLICATION_SCHEMA, on_new="rescue", optional=OPTIONAL)
        name = f"batch={_stamp(low) if low else 'initial'}__{_stamp(high)}.parquet"
        path = raw(root, "mongo", "applications", name)
        rows_written = lake.write_parquet(
            conformed, path, lake.arrow_schema(APPLICATION_SCHEMA, rescued=True)
        )
        file = str(path.relative_to(root))
        state.set("mongo.applications.watermark", high.isoformat())  # only after the file exists

    # Hard deletes: compare the set of keys in the source with the keys in the lake.
    import duckdb

    source_ids = {d["_id"] for d in coll.find({}, {"_id": 1})}
    lake_glob = raw(root, "mongo", "applications", "*.parquet")
    deleted_glob = raw(root, "mongo", "applications_deleted", "*.parquet")
    con = duckdb.connect()
    lake_ids = {r[0] for r in con.execute(f"SELECT DISTINCT application_id FROM '{lake_glob}'").fetchall()}
    known_deleted: set[str] = set()
    if deleted_glob.parent.exists() and any(deleted_glob.parent.glob("*.parquet")):
        known_deleted = {r[0] for r in con.execute(f"SELECT application_id FROM '{deleted_glob}'").fetchall()}
    gone = sorted(lake_ids - source_ids - known_deleted)
    if gone:
        rows = [{"application_id": g, "detected_at": as_of} for g in gone]
        lake.write_parquet(
            rows, raw(root, "mongo", "applications_deleted", f"detected={_stamp(as_of)}.parquet"),
            lake.arrow_schema(DELETED_SCHEMA),
        )  # fmt: skip
    return MongoResult((low, high), rows_written, len(gone), report, file)


@dataclass
class CassandraResult:
    days: tuple[date, date] | None
    partitions: int
    rows: int


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def extract_cassandra_days(src: Sources, root: Path, start: date, end: date) -> CassandraResult:
    """(Re)write one Parquet file per day partition in [start, end]."""
    s = src.cassandra
    query = s.prepare(
        "SELECT event_id, loan_id, event_time, event_day, ingested_at, instalment_no, amount_cents, method "
        f"FROM {KEYSPACE}.payment_events_by_day WHERE event_day = ?"
    )
    query.fetch_size = 5_000
    partitions = rows = 0
    schema = lake.arrow_schema(PAYMENT_SCHEMA)
    futures = [(day, s.execute_async(query, (day,))) for day in _days(start, end)]
    for day, future in futures:
        result = [
            {
                "event_id": str(r.event_id), "loan_id": r.loan_id,
                "event_time": r.event_time.replace(tzinfo=UTC), "event_day": r.event_day.date(),
                "ingested_at": r.ingested_at.replace(tzinfo=UTC), "instalment_no": r.instalment_no,
                "amount_cents": r.amount_cents, "method": r.method,
            }
            for r in future.result()
        ]  # fmt: skip
        path = raw(root, "cassandra", "payment_events", f"event_day={day.isoformat()}", "part-0.parquet")
        if result:
            rows += lake.write_parquet(result, path, schema)
            partitions += 1
        elif path.exists():
            path.unlink()  # the day is empty in the source now: the lake must agree
    return CassandraResult((start, end), partitions, rows)


def extract_cassandra(src: Sources, root: Path, state: lake.State, as_of: datetime) -> CassandraResult:
    last = state.get("cassandra.payment_events.last_day")
    end = as_of.date()
    # First run: every day since go-live. Later runs: re-read the last few days too,
    # because late events land in day partitions that were already extracted.
    start = GO_LIVE if last is None else date.fromisoformat(last) - timedelta(days=LOOKBACK_DAYS)
    result = extract_cassandra_days(src, root, start, end)
    state.set("cassandra.payment_events.last_day", end.isoformat())
    return result


def extract_neo4j(src: Sources, root: Path, as_of: datetime) -> int:
    from nosqlde.labs.ch06_neo4j import EDGES

    edges = [dict(r) for r in src.neo4j.execute_query(EDGES).records]
    path = raw(root, "neo4j", "identity_edges", f"snapshot={as_of.date().isoformat()}", "part-0.parquet")
    return lake.write_parquet(edges, path, lake.arrow_schema(EDGE_SCHEMA))
