"""Chapter 4 lab: Apache Cassandra, a wide-column store, and extracting from it at scale.

Run with `make lab-04` (Cassandra must be up: `make up-04`). The lab drops and
recreates the keyspaces `larkspur_ch04` and `larkspur_ch04_rf3`, so it is safe to re-run.
"""

from __future__ import annotations

import itertools
import re
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import duckdb

from nosqlde import clients, datagen, lake
from nosqlde.config import SETTINGS
from nosqlde.console import heading, say, step, table

KS = "larkspur_ch04"
MIN_TOKEN = -(2**63)
MAX_TOKEN = 2**63 - 1

PAYMENT_COLUMNS = "loan_id, event_time, event_id, event_day, instalment_no, amount_cents, method"


# Step 4.1: one table per access pattern, the same rows in each.
DDL = {
    "payments_by_loan": "PRIMARY KEY ((loan_id), event_time, event_id)) "
    "WITH CLUSTERING ORDER BY (event_time DESC, event_id ASC)",
    "payments_by_day": "PRIMARY KEY ((event_day), event_time, event_id))",
    "payments_by_method": "PRIMARY KEY ((method), event_time, event_id))",
}


def create_and_load(s: Any, events: list[dict[str, Any]]) -> int:
    """Create step 4.1's three tables in the session's keyspace and insert every event."""
    from cassandra.concurrent import execute_concurrent_with_args

    for name, key in DDL.items():
        s.execute(
            f"CREATE TABLE {name} (loan_id text, event_time timestamp, event_id uuid, "
            f"event_day date, instalment_no int, amount_cents bigint, method text, {key}"
        )
    params = [
        (
            e["loan_id"], e["event_time"], uuid.UUID(e["event_id"]), e["event_day"],
            e["instalment_no"], e["amount_cents"], e["method"],
        )
        for e in events
    ]  # fmt: skip
    for name in DDL:
        prepared = s.prepare(f"INSERT INTO {name} ({PAYMENT_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)")
        execute_concurrent_with_args(s, prepared, params, concurrency=64)
    return len(params)


def make_work_queue(s: Any) -> None:
    """Step 4.5: a table used as a queue: 2,000 rows in one partition, 1,500 deleted."""
    from cassandra.concurrent import execute_concurrent_with_args

    s.execute(
        "CREATE TABLE IF NOT EXISTS work_queue (queue text, item int, payload text, PRIMARY KEY ((queue), item))"
    )
    ins = s.prepare("INSERT INTO work_queue (queue, item, payload) VALUES ('documents', ?, 'pending')")
    execute_concurrent_with_args(s, ins, [(i,) for i in range(2_000)], concurrency=64)
    dele = s.prepare("DELETE FROM work_queue WHERE queue = 'documents' AND item = ?")
    execute_concurrent_with_args(s, dele, [(i,) for i in range(1_500)], concurrency=64)


def token_ranges(n: int) -> list[tuple[int, int]]:
    """Split the Murmur3 token ring into n contiguous (start, end] ranges."""
    width = (MAX_TOKEN - MIN_TOKEN) // n
    bounds = [MIN_TOKEN + i * width for i in range(n)] + [MAX_TOKEN]
    return list(itertools.pairwise(bounds))


def trace_lines(result: Any, needle: str) -> list[str]:
    """Trace events whose text contains `needle` (tracing must be on for the query)."""
    trace = result.get_query_trace()
    return [e.description for e in trace.events if needle in e.description]


def run() -> None:
    from cassandra import ConsistencyLevel
    from cassandra.query import SimpleStatement

    heading("Chapter 4 lab: Apache Cassandra")
    s = clients.cassandra()
    world = datagen.generate(seed=42)
    events = world.payments
    out = SETTINGS.lake_dir / "ch04"

    settings = {
        r.name: r.value
        for r in s.execute(
            "SELECT name, value FROM system_views.settings WHERE name IN "
            "('num_tokens', 'tombstone_warn_threshold', 'tombstone_failure_threshold', 'paxos_variant')"
        )
    }
    release = s.execute("SELECT release_version FROM system.local").one().release_version
    say(f"Cassandra {release}; server settings (system_views.settings): {settings}")

    # ------------------------------------------------------------------ 4.1
    step("4.1", "Model the tables from the queries, then load them")
    s.execute(f"DROP KEYSPACE IF EXISTS {KS}")
    s.execute(
        f"CREATE KEYSPACE {KS} WITH replication = {{'class': 'SimpleStrategy', 'replication_factor': 1}}"
    )
    s.set_keyspace(KS)
    for name, key in DDL.items():
        say(f"CREATE TABLE {name} (... {key.split(' WITH')[0]}")
    start = time.perf_counter()
    inserted = create_and_load(s, events)
    say(f"inserted {inserted} payment events into each of the 3 tables in {time.perf_counter() - start:.1f}s")

    # ------------------------------------------------------------------ 4.2
    step("4.2", "Partition key and clustering key")
    rows = list(
        s.execute(
            "SELECT event_time, instalment_no, amount_cents FROM payments_by_loan "
            "WHERE loan_id = 'L0000006' LIMIT 3"
        )
    )
    say("latest 3 payments of loan L0000006 (one partition, already sorted newest first):")
    table(
        [[r.event_time, r.instalment_no, r.amount_cents] for r in rows],
        ["event_time", "instalment_no", "amount_cents"],
    )
    try:
        s.execute("SELECT * FROM payments_by_loan WHERE amount_cents > 215000")
    except Exception as err:
        say(f"filter on a non-key column -> {type(err).__name__}: {str(err).split('message=')[-1][:110]}...")

    # ------------------------------------------------------------------ 4.3
    step("4.3", "Why ALLOW FILTERING is a trap")
    keyed = s.execute("SELECT * FROM payments_by_loan WHERE loan_id = 'L0000006'", trace=True)
    keyed_rows = len(list(keyed))
    filtered = s.execute(
        SimpleStatement(
            "SELECT * FROM payments_by_loan WHERE amount_cents > 215000 ALLOW FILTERING",
            fetch_size=100_000,
        ),
        trace=True,
    )
    filtered_rows = len(list(filtered))
    table(
        [
            ["WHERE loan_id = 'L0000006'", keyed_rows, "; ".join(trace_lines(keyed, "live rows"))],
            [
                "WHERE amount_cents > 215000 ALLOW FILTERING",
                filtered_rows,
                "; ".join(trace_lines(filtered, "live rows") + trace_lines(filtered, "range requests")),
            ],
        ],
        ["query", "rows returned", "query trace says"],
    )

    # ------------------------------------------------------------------ 4.4
    step("4.4", "Hot partitions: a low-cardinality partition key")
    by_method = sorted(
        (
            (r.method, r.count)
            for r in s.execute("SELECT method, count(*) AS count FROM payments_by_method GROUP BY method")
        ),
        key=lambda x: -x[1],
    )
    day_sizes = Counter(e["event_day"] for e in events)
    loan_sizes = Counter(e["loan_id"] for e in events)
    table(
        [
            [
                "payments_by_method",
                "method",
                len(by_method),
                by_method[0][1],
                f"{by_method[0][1] / len(events):.0%}",
            ],
            [
                "payments_by_day",
                "event_day",
                len(day_sizes),
                max(day_sizes.values()),
                f"{max(day_sizes.values()) / len(events):.1%}",
            ],
            [
                "payments_by_loan",
                "loan_id",
                len(loan_sizes),
                max(loan_sizes.values()),
                f"{max(loan_sizes.values()) / len(events):.2%}",
            ],
        ],
        ["table", "partition key", "partitions", "rows in largest", "share of all rows"],
    )
    say("rows per partition in payments_by_method: " + ", ".join(f"{m}={c}" for m, c in by_method))

    # ------------------------------------------------------------------ 4.5
    step("4.5", "Tombstones: deletes are writes, and reads pay for them")
    make_work_queue(s)
    say("inserted 2000 rows in one partition, then deleted 1500 of them one by one (a queue pattern)")
    res = s.execute(
        SimpleStatement("SELECT * FROM work_queue WHERE queue = 'documents'", fetch_size=5_000), trace=True
    )
    live = len(list(res))
    say(f"SELECT the partition: {live} rows returned")
    for w in res.response_future.warnings or []:
        say(f"server warning sent to the client: {w.split(' for query')[0]} ({w.split('(')[-1]}")
    gc = s.execute(
        "SELECT gc_grace_seconds FROM system_schema.tables WHERE keyspace_name = %s AND table_name = 'work_queue'",
        (KS,),
    ).one()
    say(
        f"gc_grace_seconds = {gc.gc_grace_seconds} ({gc.gc_grace_seconds / 86_400:.0f} days): tombstones stay at least this long"
    )

    # ------------------------------------------------------------------ 4.6
    step("4.6", "Consistency levels on a single node")
    s.execute("DROP KEYSPACE IF EXISTS larkspur_ch04_rf3")
    s.execute(
        "CREATE KEYSPACE larkspur_ch04_rf3 WITH replication = "
        "{'class': 'SimpleStrategy', 'replication_factor': 3}"
    )
    results = []
    for ks, rf in ((KS, 1), ("larkspur_ch04_rf3", 3)):
        s.execute(f"CREATE TABLE IF NOT EXISTS {ks}.t (k text PRIMARY KEY, v text)")
        for cl_name in ("ONE", "QUORUM", "ALL"):
            stmt = SimpleStatement(
                f"INSERT INTO {ks}.t (k, v) VALUES ('a', 'b')",
                consistency_level=getattr(ConsistencyLevel, cl_name),
            )
            try:
                s.execute(stmt)
                outcome = "ok"
            except Exception as err:
                detail = str(err)
                need = re.search(r"required_replicas\W+(\d+)", detail)
                alive = re.search(r"alive_replicas\W+(\d+)", detail)
                outcome = (
                    f"Unavailable: needs {need.group(1) if need else '?'} replicas, "
                    f"{alive.group(1) if alive else '?'} alive"
                )
            results.append([f"RF={rf}", cl_name, outcome])
    table(results, ["keyspace", "write consistency", "result"])

    # ------------------------------------------------------------------ 4.7
    step("4.7", "Lightweight transactions (compare-and-set)")
    s.execute("CREATE TABLE IF NOT EXISTS loan_status (loan_id text PRIMARY KEY, status text, version int)")
    s.execute("TRUNCATE loan_status")
    r1 = s.execute(
        "INSERT INTO loan_status (loan_id, status, version) VALUES ('L0000006', 'active', 1) IF NOT EXISTS"
    )
    r2 = s.execute(
        "INSERT INTO loan_status (loan_id, status, version) VALUES ('L0000006', 'closed', 1) IF NOT EXISTS"
    )
    r3 = s.execute(
        "UPDATE loan_status SET status = 'closed', version = 2 WHERE loan_id = 'L0000006' IF version = 1"
    )
    r4 = s.execute(
        "UPDATE loan_status SET status = 'written_off', version = 2 WHERE loan_id = 'L0000006' IF version = 1"
    )
    table(
        [
            ["INSERT ... IF NOT EXISTS", r1.was_applied, ""],
            ["INSERT ... IF NOT EXISTS (again)", r2.was_applied, f"existing row: status={r2.one().status}"],
            ["UPDATE ... IF version = 1", r3.was_applied, ""],
            [
                "UPDATE ... IF version = 1 (stale writer)",
                r4.was_applied,
                f"current version={r4.one().version}",
            ],
        ],
        ["statement", "[applied]", "returned"],
    )

    # ------------------------------------------------------------------ 4.8
    step("4.8", "Full extraction by token range, in parallel")
    sample = list(s.execute("SELECT DISTINCT loan_id, token(loan_id) AS t FROM payments_by_loan LIMIT 3"))
    say(
        "rows come back in token order, not loan_id order: "
        + ", ".join(f"{r.loan_id} -> token {r.t}" for r in sample)
    )
    ranges = token_ranges(16)
    query = s.prepare(
        f"SELECT {PAYMENT_COLUMNS} FROM payments_by_loan WHERE token(loan_id) > ? AND token(loan_id) <= ?"
    )
    query.fetch_size = 2_000
    schema = {
        "loan_id": "string", "event_time": "timestamp", "event_id": "string", "event_day": "date",
        "instalment_no": "int", "amount_cents": "int", "method": "string",
    }  # fmt: skip

    def extract(i: int) -> int:
        lo, hi = ranges[i]
        rows = [
            {
                "loan_id": r.loan_id,
                "event_time": r.event_time,
                "event_id": str(r.event_id),
                "event_day": r.event_day.date(),
                "instalment_no": r.instalment_no,
                "amount_cents": r.amount_cents,
                "method": r.method,
            }
            for r in s.execute(query, (lo, hi))
        ]
        return lake.write_parquet(
            rows, out / "payments" / f"range={i:02d}.parquet", lake.arrow_schema(schema)
        )

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=8) as pool:
        counts = list(pool.map(extract, range(len(ranges))))
    took = time.perf_counter() - start
    say(
        f"16 token ranges, 8 threads: {sum(counts)} rows in {took:.2f}s; rows per range min={min(counts)} max={max(counts)}"
    )
    con = duckdb.connect()
    total, distinct, cents = con.execute(
        f"SELECT count(*), count(DISTINCT event_id), sum(amount_cents) FROM '{out}/payments/*.parquet'"
    ).fetchone() or (0, 0, 0)
    say(f"DuckDB over the extract: {total} rows, {distinct} distinct event_id, sum(amount_cents)={cents}")
    say(f"source events: {len(events)}, sum(amount_cents)={sum(e['amount_cents'] for e in events)}")
    s.cluster.shutdown()
