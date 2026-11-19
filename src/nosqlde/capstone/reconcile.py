"""Reconcile each operational source against the lake model.

Each check reads the same columns from both sides, in whatever order each side
returns them, and compares row count and order-independent checksum
(nosqlde.recon). A count mismatch means rows were lost or duplicated; a checksum
mismatch with equal counts means values changed in transit.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from nosqlde.capstone import model
from nosqlde.capstone.sources import KEYSPACE, MONGO_DB, Sources
from nosqlde.labs.ch04_cassandra import token_ranges
from nosqlde.labs.ch06_neo4j import EDGES
from nosqlde.recon import Fingerprint, ReconResult, reconcile


def _cassandra_events(src: Sources) -> Iterator[tuple[Any, ...]]:
    s = src.cassandra
    q = s.prepare(
        f"SELECT event_id, loan_id, event_time, amount_cents FROM {KEYSPACE}.payment_events_by_loan "
        "WHERE token(loan_id) > ? AND token(loan_id) <= ?"
    )
    for lo, hi in token_ranges(16):
        for r in s.execute(q, (lo, hi)):
            yield (str(r.event_id), r.loan_id, r.event_time, r.amount_cents)


def run_all(src: Sources, root: Path) -> list[ReconResult]:
    con = model.connect(root)
    results: list[ReconResult] = []
    apps = src.mongo[MONGO_DB].applications

    results.append(
        reconcile(
            "mongo applications (id, status, updated_at)",
            ((d["_id"], d["status"], d["updated_at"]) for d in apps.find({}, {"status": 1, "updated_at": 1})),
            con.execute("SELECT application_id, status, updated_at FROM applications_current").fetchall(),
        )
    )
    results.append(
        reconcile(
            "mongo loans (id, principal, rate)",
            (
                (d["loan"]["loan_id"], d["loan"]["principal"], d["loan"]["annual_rate"])
                for d in apps.find({"loan": {"$exists": True}}, {"loan": 1})
            ),
            con.execute("SELECT loan_id, principal, annual_rate FROM loans").fetchall(),
        )
    )
    results.append(
        reconcile(
            "cassandra payment events",
            _cassandra_events(src),
            con.execute("SELECT event_id, loan_id, event_time, amount_cents FROM payment_events").fetchall(),
        )
    )
    results.append(
        reconcile(
            "cassandra daily counters vs lake sums",
            (
                (r.event_day.date(), r.events, r.amount_cents)
                for r in src.cassandra.execute(
                    f"SELECT event_day, events, amount_cents FROM {KEYSPACE}.payment_totals_by_day"
                )
            ),
            con.execute(
                "SELECT event_day, count(*), sum(amount_cents) FROM payment_events GROUP BY event_day"
            ).fetchall(),
        )
    )
    results.append(
        reconcile(
            "neo4j identity edges",
            (tuple(r.values()) for r in src.neo4j.execute_query(EDGES).records),
            con.execute("SELECT application_id, borrower_id, kind, value FROM identity_edges").fetchall(),
        )
    )
    dedup_keys = sum(1 for _ in src.redis.scan_iter("ops:dedup:*", count=2_000))
    lake_events = int((con.execute("SELECT count(*) FROM payment_events").fetchone() or (0,))[0])
    results.append(
        ReconResult(
            "redis dedup keys vs lake events (count)", Fingerprint(dedup_keys, 0), Fingerprint(lake_events, 0)
        )
    )
    con.close()
    return results
