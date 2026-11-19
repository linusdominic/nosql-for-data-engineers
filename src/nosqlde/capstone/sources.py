"""The operational systems of Larkspur Lending (fictional), simulated.

* MongoDB `larkspur_ops.applications`: the origination system's application documents.
* Redis stream `ops:payments:incoming` (db 7): the payment gateway's event feed. It
  delivers at least once, so some events arrive twice.
* Cassandra keyspace `larkspur_ops`: the servicing system's payment events, written by
  an ingest worker that reads the Redis stream, skips duplicates with Redis
  idempotency keys, and keeps a per-day counter table.
* Neo4j: the fraud team's identity graph, synced from the application documents.

`advance_to(t)` moves every system forward to time t using the deterministic world
from nosqlde.datagen, so two runs of the capstone see exactly the same changes.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

import redis
from neo4j import Driver
from pymongo import MongoClient, ReplaceOne

from nosqlde import datagen
from nosqlde.labs.ch06_neo4j import CONSTRAINTS, LOAD, reset

MONGO_DB = "larkspur_ops"
KEYSPACE = "larkspur_ops"
REDIS_DB = 7
STREAM = "ops:payments:incoming"
GROUP = "cassandra-ingest"
DEDUP_TTL_S = 30 * 86_400

EVENT_COLUMNS = "event_id, loan_id, event_time, event_day, ingested_at, instalment_no, amount_cents, method"


@dataclass
class IngestStats:
    delivered: int = 0
    redelivered: int = 0
    duplicates_skipped: int = 0
    written: int = 0


@dataclass
class SourceChanges:
    as_of: datetime
    applications_inserted: int = 0
    applications_updated: int = 0
    applications_deleted: list[str] = field(default_factory=list)
    ingest: IngestStats = field(default_factory=IngestStats)


@dataclass
class Sources:
    mongo: MongoClient[dict[str, Any]]
    cassandra: Any
    redis: redis.Redis
    neo4j: Driver
    world: datagen.World
    as_of: datetime | None = None
    erased: set[str] = field(default_factory=set)

    # ------------------------------------------------------------ setup
    def reset(self) -> None:
        """Drop everything the capstone owns, so every run starts from the same place."""
        self.mongo.drop_database(MONGO_DB)
        self.mongo[MONGO_DB].applications.create_index("updated_at")
        s = self.cassandra
        s.execute(f"DROP KEYSPACE IF EXISTS {KEYSPACE}")
        s.execute(
            f"CREATE KEYSPACE {KEYSPACE} WITH replication = "
            "{'class': 'SimpleStrategy', 'replication_factor': 1}"
        )
        cols = (
            "event_id uuid, loan_id text, event_time timestamp, event_day date, "
            "ingested_at timestamp, instalment_no int, amount_cents bigint, method text"
        )
        # Query-first: one table per access pattern. by_day exists so that an
        # incremental extract can read "the last few days" partition by partition.
        s.execute(
            f"CREATE TABLE {KEYSPACE}.payment_events_by_day ({cols}, PRIMARY KEY ((event_day), event_time, event_id))"
        )
        s.execute(
            f"CREATE TABLE {KEYSPACE}.payment_events_by_loan ({cols}, PRIMARY KEY ((loan_id), event_time, event_id)) "
            "WITH CLUSTERING ORDER BY (event_time DESC, event_id ASC)"
        )
        s.execute(
            f"CREATE TABLE {KEYSPACE}.payment_totals_by_day "
            "(event_day date PRIMARY KEY, events counter, amount_cents counter)"
        )
        self.redis.flushdb()
        self.redis.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        reset(self.neo4j)
        for stmt in CONSTRAINTS:
            self.neo4j.execute_query(stmt)
        self.as_of = None
        self.erased = set()

    # ------------------------------------------------------------ moving time forward
    def advance_to(self, t: datetime, erase: int = 0) -> SourceChanges:
        """Apply every change between the previous as_of and t to all four systems."""
        changes = SourceChanges(as_of=t)
        self._advance_mongo(t, changes, erase)
        self._publish_payments(t)
        changes.ingest = self._ingest_payments(crash_after=200)
        self._sync_graph()
        self.as_of = t
        return changes

    def _advance_mongo(self, t: datetime, changes: SourceChanges, erase: int) -> None:
        coll = self.mongo[MONGO_DB].applications
        ops = []
        for app in self.world.applications:
            if app["application_id"] in self.erased:
                continue
            now = datagen.application_as_of(app, t)
            if now is None:
                continue
            before = datagen.application_as_of(app, self.as_of) if self.as_of else None
            if before is None:
                changes.applications_inserted += 1
            elif before["updated_at"] != now["updated_at"]:
                changes.applications_updated += 1
            else:
                continue
            ops.append(ReplaceOne({"_id": now["_id"]}, now, upsert=True))
        if ops:
            coll.bulk_write(ops, ordered=False)
        if erase:
            # Erasure requests: the source hard-deletes withdrawn applications.
            victims = [
                d["_id"] for d in coll.find({"status": "withdrawn"}, {"_id": 1}).sort("_id").limit(erase)
            ]
            coll.delete_many({"_id": {"$in": victims}})
            self.erased.update(victims)
            changes.applications_deleted = victims

    def _publish_payments(self, t: datetime) -> None:
        """The gateway: XADD every event that arrived in (as_of, t], some of them twice."""
        rng = random.Random(f"gateway-{t.isoformat()}")
        pipe = self.redis.pipeline()
        for e in self.world.payments:
            if not ((self.as_of is None or e["ingested_at"] > self.as_of) and e["ingested_at"] <= t):
                continue
            fields = {
                "event_id": e["event_id"],
                "loan_id": e["loan_id"],
                "event_time": e["event_time"].isoformat(),
                "ingested_at": e["ingested_at"].isoformat(),
                "instalment_no": e["instalment_no"],
                "amount_cents": e["amount_cents"],
                "method": e["method"],
            }
            copies = 2 if rng.random() < 0.03 else 1  # at-least-once: ~3% sent twice
            for _ in range(copies):
                pipe.xadd(STREAM, cast(Any, fields))
        pipe.execute()

    def _ingest_payments(self, crash_after: int) -> IngestStats:
        """The ingest worker: Redis stream -> Cassandra, with idempotency keys.

        worker-1 reads `crash_after` entries and dies before acknowledging them.
        worker-2 processes everything else, then claims worker-1's entries.
        """
        stats = IngestStats()
        r = self.redis
        if crash_after:
            lost: Any = r.xreadgroup(GROUP, "worker-1", {STREAM: ">"}, count=crash_after)
            stats.delivered += len(lost[0][1]) if lost else 0
        while True:
            batch: Any = r.xreadgroup(GROUP, "worker-2", {STREAM: ">"}, count=500)
            if not batch:
                break
            stats.delivered += len(batch[0][1])
            self._process(batch[0][1], stats)
        start = "0-0"
        while True:
            claimed: Any = r.xautoclaim(STREAM, GROUP, "worker-2", min_idle_time=0, start_id=start, count=500)
            if claimed[1]:
                stats.delivered += len(claimed[1])
                stats.redelivered += len(claimed[1])
                self._process(claimed[1], stats)
            start = claimed[0]
            if start == "0-0":
                break
        return stats

    def _process(self, entries: list[Any], stats: IngestStats) -> None:
        from cassandra.concurrent import execute_concurrent

        r = self.redis
        pipe = r.pipeline()
        for _, fields in entries:
            pipe.exists(f"ops:dedup:{fields['event_id']}")
        seen = pipe.execute()
        fresh: list[tuple[str, dict[str, str]]] = []
        batch_ids: set[str] = set()
        for (entry_id, fields), already in zip(entries, seen, strict=True):
            if already or fields["event_id"] in batch_ids:
                stats.duplicates_skipped += 1
            else:
                fresh.append((entry_id, fields))
                batch_ids.add(fields["event_id"])
        s = self.cassandra
        by_day = s.prepare(
            f"INSERT INTO {KEYSPACE}.payment_events_by_day ({EVENT_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        )
        by_loan = s.prepare(
            f"INSERT INTO {KEYSPACE}.payment_events_by_loan ({EVENT_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        )
        counter = s.prepare(
            f"UPDATE {KEYSPACE}.payment_totals_by_day SET events = events + 1, amount_cents = amount_cents + ? "
            "WHERE event_day = ?"
        )
        statements = []
        for _, f in fresh:
            event_time = datetime.fromisoformat(f["event_time"])
            values = (
                uuid.UUID(f["event_id"]), f["loan_id"], event_time, event_time.date(),
                datetime.fromisoformat(f["ingested_at"]), int(f["instalment_no"]), int(f["amount_cents"]), f["method"],
            )  # fmt: skip
            statements += [
                (by_day, values),
                (by_loan, values),
                (counter, (int(f["amount_cents"]), event_time.date())),
            ]
        if statements:
            for ok, result in execute_concurrent(s, statements, concurrency=64, raise_on_first_error=True):
                if not ok:
                    raise RuntimeError(result)
        # Only after the writes succeeded: remember the event, then acknowledge.
        pipe = r.pipeline()
        for _, f in fresh:
            pipe.set(f"ops:dedup:{f['event_id']}", 1, ex=DEDUP_TTL_S)
        for entry_id, _ in entries:
            pipe.xack(STREAM, GROUP, entry_id)
        pipe.execute()
        stats.written += len(fresh)

    def _sync_graph(self) -> None:
        """The fraud team's sync job: MERGE every current application into the graph."""
        docs = list(self.mongo[MONGO_DB].applications.find({}))
        rows = []
        for d in docs:
            a = d["address"]
            rows.append(
                {
                    "application_id": d["application_id"], "borrower_id": d["borrower"]["borrower_id"],
                    "name": d["borrower"]["full_name"], "status": d["status"], "product": d["product"],
                    "submitted_at": d["submitted_at"].isoformat(), "phone": d["contact"]["phone"],
                    "device_id": d["device_id"], "address_key": f"{a['line1']}, {a['town']}, {a['postcode']}",
                }
            )  # fmt: skip
        for i in range(0, len(rows), 500):
            self.neo4j.execute_query(LOAD, rows=rows[i : i + 500])
        if self.erased:
            self.neo4j.execute_query(
                "MATCH (a:Application) WHERE a.application_id IN $ids DETACH DELETE a",
                ids=sorted(self.erased),
            )
