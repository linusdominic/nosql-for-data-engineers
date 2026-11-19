"""Check chapter 4's exercises against Cassandra (keyspace `larkspur_ch04_check`)."""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime

from nosqlde import checks, clients, datagen

KS = "larkspur_ch04_check"
MIN_TOKEN = -(2**63)
MAX_TOKEN = 2**63 - 1


def run(solutions: bool = False) -> int:
    from cassandra.concurrent import execute_concurrent_with_args

    checker, answers = checks.start("Chapter 4 (Cassandra)", "ch04_cassandra.py", solutions)
    s = clients.cassandra()
    s.execute(f"DROP KEYSPACE IF EXISTS {KS}")
    s.execute(
        f"CREATE KEYSPACE {KS} WITH replication = {{'class': 'SimpleStrategy', 'replication_factor': 1}}"
    )
    s.set_keyspace(KS)
    world = datagen.generate(seed=42)
    borrower_of = {
        a["loan"]["loan_id"]: a["borrower"]["borrower_id"] for a in world.applications if a.get("loan")
    }

    def ex1() -> str:
        s.execute(answers.payments_by_borrower_month_ddl())
        cols = {
            r.column_name: (r.kind, r.position, r.clustering_order, r.type)
            for r in s.execute(
                "SELECT column_name, kind, position, clustering_order, type FROM system_schema.columns "
                "WHERE keyspace_name = %s AND table_name = 'payments_by_borrower_month'",
                (KS,),
            )
        }
        assert cols, "table payments_by_borrower_month was not created"
        pk = sorted((v[1], k) for k, v in cols.items() if v[0] == "partition_key")
        ck = sorted((v[1], k, v[2]) for k, v in cols.items() if v[0] == "clustering")
        assert [k for _, k in pk] == ["borrower_id", "month"], (
            f"partition key should be (borrower_id, month) so one query reads one partition; got {[k for _, k in pk]}"
        )
        assert ck and ck[0][1] == "event_time" and ck[0][2] == "desc", (
            f"first clustering column should be event_time DESC; got {[(k, o) for _, k, o in ck]}"
        )
        assert any(k == "event_id" for _, k, _ in ck), (
            "event_id must be part of the clustering key, or two payments at the same time overwrite each other"
        )
        same_time = datetime(2025, 3, 5, 12, 0, tzinfo=UTC)
        ins = s.prepare(
            "INSERT INTO payments_by_borrower_month (borrower_id, month, event_time, event_id, loan_id, amount_cents) "
            "VALUES (?, ?, ?, ?, ?, ?)"
        )
        rows = [
            (borrower_of[e["loan_id"]], e["event_time"].strftime("%Y-%m"), e["event_time"],
             uuid.UUID(e["event_id"]), e["loan_id"], e["amount_cents"])
            for e in world.payments[:3000]
        ]  # fmt: skip
        rows += [("B-TEST", "2025-03", same_time, uuid.uuid4(), "L-T", 100) for _ in range(2)]
        execute_concurrent_with_args(s, ins, rows, concurrency=64)
        got = list(
            s.execute(
                "SELECT event_time FROM payments_by_borrower_month WHERE borrower_id = 'B-TEST' AND month = '2025-03'"
            )
        )
        assert len(got) == 2, f"two payments at the same instant should both be stored, found {len(got)}"
        b, m = rows[0][0], rows[0][1]
        times = [
            r.event_time
            for r in s.execute(
                "SELECT event_time FROM payments_by_borrower_month WHERE borrower_id = %s AND month = %s",
                (b, m),
            )
        ]
        assert times == sorted(times, reverse=True), "rows must come back newest first"
        return "partition (borrower_id, month), clustering event_time DESC, event_id"

    def ex2() -> str:
        for n in (1, 4, 16, 7):
            ranges = answers.token_ranges(n)
            assert len(ranges) == n, f"token_ranges({n}) returned {len(ranges)} ranges"
            assert ranges[0][0] == MIN_TOKEN, f"first range must start at MIN_TOKEN, starts at {ranges[0][0]}"
            assert ranges[-1][1] == MAX_TOKEN, f"last range must end at MAX_TOKEN, ends at {ranges[-1][1]}"
            for (_, end), (start, _) in itertools.pairwise(ranges):
                assert end == start, f"gap or overlap between ranges: ...{end}] then ({start}..."
            assert all(a < b for a, b in ranges), "every range must have start < end"
        return "contiguous, no gaps, no overlaps, for n = 1, 4, 7, 16"

    def ex3() -> str:
        s.execute("CREATE TABLE IF NOT EXISTS scan_me (loan_id text, n int, PRIMARY KEY ((loan_id), n))")
        ins = s.prepare("INSERT INTO scan_me (loan_id, n) VALUES (?, ?)")
        data = [(f"L{i:05d}", j) for i in range(600) for j in range(3)]
        execute_concurrent_with_args(s, ins, data, concurrency=64)
        rows = answers.scan_by_token(s, "scan_me", "loan_id", 12)
        keys = [(r.loan_id, r.n) for r in rows]
        assert len(keys) == len(data), f"expected {len(data)} rows, got {len(keys)}"
        assert len(set(keys)) == len(data), f"{len(keys) - len(set(keys))} rows were read twice"
        return f"{len(keys)} rows from 12 ranges, none missing, none duplicated"

    def ex4() -> str:
        s.execute("CREATE TABLE IF NOT EXISTS payment_claims (event_id uuid PRIMARY KEY, loan_id text)")
        eid = uuid.uuid4()
        first = answers.claim_payment(s, eid, "L0000006")
        second = answers.claim_payment(s, eid, "L0000007")
        assert first is True, f"first claim should return True, got {first!r}"
        assert second is False, f"second claim should return False, got {second!r}"
        row = s.execute("SELECT loan_id FROM payment_claims WHERE event_id = %s", (eid,)).one()
        assert row.loan_id == "L0000006", f"the first writer must win; loan_id is now {row.loan_id}"
        return "first claim applied, second rejected, first writer's value kept"

    checker.run("4.1 payments_by_borrower_month_ddl", ex1)
    checker.run("4.2 token_ranges", ex2)
    checker.run("4.3 scan_by_token", ex3)
    checker.run("4.4 claim_payment", ex4)
    s.execute(f"DROP KEYSPACE IF EXISTS {KS}")
    s.cluster.shutdown()
    return checker.finish()
