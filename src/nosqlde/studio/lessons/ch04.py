"""Chapter 4 in the studio: Cassandra, in a CQL console (keyspace larkspur_studio)."""

from __future__ import annotations

import re

from nosqlde.studio.checking import CheckRun, Outcome, failed, passed
from nosqlde.studio.lessons.model import Custom, Example, Exercise, GuideRef, Lesson, Match, Step, Verify
from nosqlde.studio.lessons.prepare import KEYSPACE, prepare_cassandra
from nosqlde.studio.runners.base import RunResult

FIRST_RANGE_END = -(2**63) + (2**64 - 1) // 16  # the lab's token_ranges(16)[0] upper bound


def check_bucketed_table(run: CheckRun, answer: RunResult) -> Outcome:
    block = run.last(
        "SELECT column_name, kind, position, clustering_order FROM system_schema.columns "
        f"WHERE keyspace_name = '{KEYSPACE}' AND table_name = 'payments_by_method_day';"
    )
    rows = block.data if isinstance(block.data, list) else []
    if not rows:
        return failed("There is no table payments_by_method_day in larkspur_studio.")
    pk = [
        r["column_name"]
        for r in sorted((r for r in rows if r["kind"] == "partition_key"), key=lambda r: r["position"])
    ]
    ck = [
        (r["column_name"], r["clustering_order"])
        for r in sorted((r for r in rows if r["kind"] == "clustering"), key=lambda r: r["position"])
    ]
    expected = {
        "partition key": ["method", "event_day"],
        "clustering": [["event_time", "desc"], ["event_id", "asc"]],
    }
    got = {"partition key": pk, "clustering": [list(c) for c in ck]}
    columns = {r["column_name"] for r in rows}
    missing = {"event_id", "event_time", "event_day", "method", "loan_id", "amount_cents"} - columns
    if missing:
        return failed(f"The table lacks the column(s) {', '.join(sorted(missing))}.", expected, got)
    if pk != ["method", "event_day"]:
        return failed(
            f"The partition key is ({', '.join(pk)}). The query names one method and one day, and a partition must stop growing: partition by both.",
            expected,
            got,
        )
    if not ck or ck[0] != ("event_time", "desc"):
        return failed(
            "The first clustering column should be event_time, descending, so a partition reads newest first.",
            expected,
            got,
        )
    if "event_id" not in [c for c, _ in ck]:
        return failed(
            "Two payments at the same instant would have the same primary key and overwrite each other: add event_id to the clustering key.",
            expected,
            got,
        )
    return passed(
        "Partition (method, event_day), clustering event_time DESC then event_id: bounded partitions, newest first, no silent overwrites.",
        expected,
        got,
    )


def check_tombstones(run: CheckRun, answer: RunResult) -> Outcome:
    last = answer.last
    data = last.data if last else None
    if not isinstance(data, dict) or "trace" not in data:
        return failed("No trace came back: start with TRACING ON; so the server records what the read did.")
    lines = [str(x) for x in data["trace"]]
    rows = data.get("rows", [])
    counts = [
        tuple(int(n) for n in m.groups())
        for line in lines
        if (m := re.search(r"Read (\d+) live rows and (\d+) tombstone cells", line))
    ]
    expected = {"rows": 500, "trace": "Read 500 live rows and 1500 tombstone cells"}
    got = {"rows": len(rows), "trace": lines}
    if not counts:
        return failed(
            "The trace has no 'Read ... live rows and ... tombstone cells' line: read the partition with a SELECT.",
            expected,
            got,
        )
    live, dead = max(counts, key=lambda c: c[1])
    if len(rows) != 500 or dead < 1500:
        return failed(
            f"The trace says {live} live rows and {dead} tombstones; read the whole 'documents' partition of work_queue.",
            expected,
            got,
        )
    return passed(
        f"To return {live} live rows the read stepped over {dead} tombstones: deletes are writes.",
        expected,
        got,
    )


LESSON = Lesson(
    id="ch04",
    number=4,
    title="Wide-column with Apache Cassandra",
    database="Cassandra 5.0",
    summary="Query-first tables, ALLOW FILTERING, hot partitions, tombstones, consistency levels, LWT and token ranges.",
    guide=GuideRef(4, "4. Wide-column with Apache Cassandra"),
    consoles=("cql",),
    services=("cassandra",),
    make_up="make up-04",
    prepare=prepare_cassandra,
    prepare_note="Drops and recreates the keyspaces larkspur_studio and larkspur_studio_rf3 with the lab's tables and 11,465 payments; takes a few seconds.",
    steps=(
        Step(
            id="query-first",
            title="Query-first modeling",
            guide=GuideRef(4, "Query-first modeling"),
            prose=(
                "A table's primary key has a **partition key**, hashed to decide which nodes hold the row, and **clustering columns**, which sort rows inside the partition. A query is cheap when it names one partition.",
                "So you design one table per query. Prepare loaded the same 11,465 payments into `payments_by_loan`, `payments_by_day` and `payments_by_method`.",
                "The console runs CQL in the keyspace `larkspur_studio`; separate statements with `;`. `TRACING ON` and `CONSISTENCY <level>` work as in cqlsh.",
            ),
            examples=(
                Example("How the table is keyed", "cql", "DESCRIBE TABLE payments_by_loan;"),
                Example(
                    "Server settings the chapter quotes",
                    "cql",
                    "SELECT name, value FROM system_views.settings\nWHERE name IN ('num_tokens', 'tombstone_warn_threshold', 'tombstone_failure_threshold', 'paxos_variant');",
                ),
            ),
            exercises=(
                Exercise(
                    id="ch04.latest",
                    number="4.1",
                    title="Latest payments of one loan",
                    console="cql",
                    task="Return the 3 latest payments of loan L0000006, newest first, with `event_time`, `instalment_no` and `amount_cents`.",
                    starter="SELECT event_time, instalment_no, amount_cents FROM payments_by_loan;",
                    hints=(
                        "Name the partition: WHERE loan_id = 'L0000006'.",
                        "The table is already clustered event_time DESC, so no ORDER BY is needed.",
                        "LIMIT 3",
                    ),
                    solution="SELECT event_time, instalment_no, amount_cents FROM payments_by_loan WHERE loan_id = 'L0000006' LIMIT 3;",
                    check=Match(fields=("event_time", "instalment_no", "amount_cents"), ordered=True),
                    wrong=(
                        "SELECT event_time, instalment_no, amount_cents FROM payments_by_loan WHERE loan_id = 'L0000006' ORDER BY event_time ASC LIMIT 3;",
                        "SELECT event_time, instalment_no, amount_cents FROM payments_by_loan WHERE loan_id = 'L0000007' LIMIT 3;",
                    ),
                    explain="One partition, read in the order it is stored on disk.",
                ),
            ),
        ),
        Step(
            id="allow-filtering",
            title="Why ALLOW FILTERING is a trap",
            guide=GuideRef(4, "Why `ALLOW FILTERING` is a trap"),
            prose=(
                "A filter on a column that is not part of the key is refused. `ALLOW FILTERING` makes Cassandra scan every partition and drop what does not match.",
                "With tracing on, the guide's trace showed 11,465 rows read to return 75, over 17 token ranges. It passes in development and times out in production.",
            ),
            examples=(
                Example(
                    "Refused without ALLOW FILTERING",
                    "cql",
                    "SELECT * FROM payments_by_loan WHERE amount_cents > 215000;",
                ),
                Example(
                    "One partition, traced",
                    "cql",
                    "TRACING ON;\nSELECT * FROM payments_by_loan WHERE loan_id = 'L0000006';\nTRACING OFF;",
                ),
            ),
            exercises=(
                Exercise(
                    id="ch04.filtering",
                    number="4.2",
                    title="Count with ALLOW FILTERING, and look at the cost",
                    console="cql",
                    task=(
                        "Count the payments in `payments_by_loan` above 215000 cents. Cassandra will make you add ALLOW FILTERING. "
                        "Turn tracing on first and read the trace under the result."
                    ),
                    starter="TRACING ON;\nSELECT count(*) FROM payments_by_loan WHERE amount_cents > 215000;",
                    hints=(
                        "Run the starter and read the error message: it tells you what to add.",
                        "ALLOW FILTERING goes at the end of the statement.",
                        "The trace line 'Read N live rows' shows how much was read.",
                    ),
                    solution="TRACING ON;\nSELECT count(*) FROM payments_by_loan WHERE amount_cents > 215000 ALLOW FILTERING;",
                    check=Match(by_position=True),
                    wrong=(
                        "SELECT count(*) FROM payments_by_loan WHERE amount_cents > 200000 ALLOW FILTERING;",
                        "SELECT count(*) FROM payments_by_loan WHERE loan_id = 'L0000006' AND amount_cents > 215000 ALLOW FILTERING;",
                    ),
                    explain="75 rows, after reading all 11,465: a full scan of every partition, which is why the default refuses it.",
                ),
            ),
        ),
        Step(
            id="hot-partitions",
            title="Hot partitions and time bucketing",
            guide=GuideRef(4, "Hot partitions and time bucketing"),
            prose=(
                "A partition is never split. A low-cardinality partition key, like the payment method, puts most of the data on the same few replicas: a **hot partition** that grows forever.",
                "The fix is **bucketing**: add a time bucket to the partition key, as `payments_by_day` does with `event_day`, or `((method, event_day))` if the query really is by method.",
            ),
            exercises=(
                Exercise(
                    id="ch04.hot",
                    number="4.3",
                    title="Rows per partition",
                    console="cql",
                    task="Count the rows in each partition of `payments_by_method`: one row per method with the method and its count.",
                    starter="SELECT method FROM payments_by_method;",
                    hints=(
                        "GROUP BY works on partition key columns.",
                        "count(*) per group.",
                        "SELECT method, count(*) FROM payments_by_method GROUP BY method;",
                    ),
                    solution="SELECT method, count(*) FROM payments_by_method GROUP BY method;",
                    check=Match(by_position=True),
                    wrong=(
                        "SELECT method, count(*) FROM payments_by_method WHERE method = 'card' GROUP BY method;",
                        "SELECT DISTINCT method FROM payments_by_method;",
                    ),
                    explain="direct_debit holds 6,864 of 11,465 rows, 60%: with replication factor 3, three nodes would hold it whatever the cluster size.",
                ),
                Exercise(
                    id="ch04.bucket",
                    number="4.4",
                    title="Design a bucketed table",
                    console="cql",
                    task=(
                        'Create `payments_by_method_day` for the query "payments made with one method on one day, newest first", with the '
                        "columns `method` text, `event_day` date, `event_time` timestamp, `event_id` uuid, `loan_id` text and `amount_cents` bigint. "
                        "Partitions must stay bounded, and two payments at the same instant must not overwrite each other."
                    ),
                    starter=(
                        "CREATE TABLE payments_by_method_day (\n  method text, event_day date, event_time timestamp,\n"
                        "  event_id uuid, loan_id text, amount_cents bigint,\n  PRIMARY KEY ((method), event_time)\n);"
                    ),
                    hints=(
                        "The query names a method and a day: both belong in the partition key, in double parentheses.",
                        "Clustering: event_time first (newest first needs WITH CLUSTERING ORDER BY), then event_id.",
                        "PRIMARY KEY ((method, event_day), event_time, event_id)) WITH CLUSTERING ORDER BY (event_time DESC, event_id ASC)",
                    ),
                    solution=(
                        "CREATE TABLE payments_by_method_day (\n  method text, event_day date, event_time timestamp,\n"
                        "  event_id uuid, loan_id text, amount_cents bigint,\n"
                        "  PRIMARY KEY ((method, event_day), event_time, event_id)\n"
                        ") WITH CLUSTERING ORDER BY (event_time DESC, event_id ASC);"
                    ),
                    check=Custom(check_bucketed_table, setup="DROP TABLE IF EXISTS payments_by_method_day;"),
                    wrong=(
                        "CREATE TABLE payments_by_method_day (method text, event_day date, event_time timestamp, event_id uuid, loan_id text, amount_cents bigint, PRIMARY KEY ((method), event_day, event_time, event_id)) WITH CLUSTERING ORDER BY (event_day DESC, event_time DESC, event_id ASC);",
                        "CREATE TABLE payments_by_method_day (method text, event_day date, event_time timestamp, event_id uuid, loan_id text, amount_cents bigint, PRIMARY KEY ((method, event_day), event_time)) WITH CLUSTERING ORDER BY (event_time DESC);",
                    ),
                    explain="The check reads the key back from system_schema.columns, like make check-04 does.",
                ),
            ),
        ),
        Step(
            id="tombstones",
            title="Tombstones",
            guide=GuideRef(4, "Tombstones"),
            prose=(
                "A delete writes a **tombstone** that hides the data until compaction removes it, at least `gc_grace_seconds` later (10 days by default). Every read steps over the tombstones in its way.",
                "`work_queue` is the lab's queue pattern: 2,000 rows inserted into one partition, then 1,500 deleted one by one.",
            ),
            examples=(
                Example(
                    "How long tombstones stay",
                    "cql",
                    f"SELECT gc_grace_seconds FROM system_schema.tables\nWHERE keyspace_name = '{KEYSPACE}' AND table_name = 'work_queue';",
                ),
            ),
            exercises=(
                Exercise(
                    id="ch04.tombstones",
                    number="4.5",
                    title="Count the tombstones a read steps over",
                    console="cql",
                    task="With tracing on, read the whole `documents` partition of `work_queue`. The check reads the trace.",
                    starter="SELECT * FROM work_queue WHERE queue = 'documents';",
                    hints=(
                        "TRACING ON; first, in the same run.",
                        "Read the partition: WHERE queue = 'documents'.",
                        "Look for 'Read ... live rows and ... tombstone cells' under the result, and the server warning.",
                    ),
                    solution="TRACING ON;\nSELECT * FROM work_queue WHERE queue = 'documents';",
                    check=Custom(check_tombstones),
                    wrong=(
                        "SELECT * FROM work_queue WHERE queue = 'documents';\nTRACING ON;",
                        "TRACING ON;\nSELECT * FROM work_queue WHERE queue = 'documents' AND item = 1600;",
                    ),
                    explain="Past tombstone_warn_threshold (1,000) the server warns; past tombstone_failure_threshold (100,000) it aborts the read.",
                ),
            ),
        ),
        Step(
            id="consistency",
            title="Consistency levels",
            guide=GuideRef(4, "Consistency levels"),
            prose=(
                "The **replication factor** (RF) is how many nodes keep each partition; the **consistency level** (CL) is how many of them must answer a query. QUORUM is floor(RF/2) + 1.",
                "`larkspur_studio_rf3` has RF 3 on this one-node cluster, so QUORUM (2) and ALL (3) cannot be reached. The Python driver's default level is `LOCAL_ONE`.",
            ),
            examples=(
                Example(
                    "QUORUM with RF 3 on one node",
                    "cql",
                    "CONSISTENCY QUORUM;\nINSERT INTO larkspur_studio_rf3.t (k, v) VALUES ('a', 'b');",
                    note="Then run CONSISTENCY LOCAL_ONE; to go back to the default.",
                ),
            ),
            exercises=(
                Exercise(
                    id="ch04.consistency",
                    number="4.6",
                    title="A write that can succeed",
                    console="cql",
                    task=(
                        "Write the row k = 'studio', v = 'written' to `larkspur_studio_rf3.t` at a consistency level that this one-node cluster "
                        "can satisfy even though RF is 3. Set the level explicitly with CONSISTENCY."
                    ),
                    starter="CONSISTENCY QUORUM;\nINSERT INTO larkspur_studio_rf3.t (k, v) VALUES ('studio', 'written');",
                    hints=(
                        "Run the starter and read the error: how many replicas are alive?",
                        "Which level needs only one replica?",
                        "CONSISTENCY ONE;",
                    ),
                    solution="CONSISTENCY ONE;\nINSERT INTO larkspur_studio_rf3.t (k, v) VALUES ('studio', 'written');",
                    check=Verify(
                        setup="CONSISTENCY ONE;\nDELETE FROM larkspur_studio_rf3.t WHERE k = 'studio';",
                        verify="CONSISTENCY ONE;\nSELECT k, v FROM larkspur_studio_rf3.t WHERE k = 'studio';",
                    ),
                    wrong=(
                        "CONSISTENCY ALL;\nINSERT INTO larkspur_studio_rf3.t (k, v) VALUES ('studio', 'written');",
                        "CONSISTENCY ONE;\nINSERT INTO larkspur_studio_rf3.t (k, v) VALUES ('studio', 'wrote');",
                    ),
                    explain="On a real RF 3 cluster, reads and writes at QUORUM overlap (2 + 2 > 3), which gives read-your-writes.",
                ),
            ),
        ),
        Step(
            id="lwt",
            title="Lightweight transactions",
            guide=GuideRef(4, "Lightweight transactions"),
            prose=(
                "A **lightweight transaction** is a compare-and-set on one partition: `INSERT ... IF NOT EXISTS` or `UPDATE ... IF column = value`. It runs Paxos and is linearizable. The result has an `[applied]` column, and the current row when it was not applied.",
                "The checks below run your statement twice, with another writer in between, so a plain write that overwrites the other writer fails.",
            ),
            examples=(
                Example(
                    "Try to insert an existing row",
                    "cql",
                    "INSERT INTO loan_status (loan_id, status, version) VALUES ('L0000006', 'closed', 1) IF NOT EXISTS;",
                ),
            ),
            exercises=(
                Exercise(
                    id="ch04.claim",
                    number="4.7",
                    title="Claim a loan id once",
                    console="cql",
                    task="Insert loan L0000099 into `loan_status` with status 'active' and version 1, but only if no row for it exists yet.",
                    starter="INSERT INTO loan_status (loan_id, status, version) VALUES ('L0000099', 'active', 1);",
                    hints=(
                        "A plain INSERT is an upsert: it silently overwrites.",
                        "Add a condition at the end of the INSERT.",
                        "... IF NOT EXISTS;",
                    ),
                    solution="INSERT INTO loan_status (loan_id, status, version) VALUES ('L0000099', 'active', 1) IF NOT EXISTS;",
                    check=Verify(
                        setup="DELETE FROM loan_status WHERE loan_id = 'L0000099';",
                        runs=2,
                        between="UPDATE loan_status SET status = 'closed', version = 5 WHERE loan_id = 'L0000099' IF EXISTS;",
                        verify="SELECT loan_id, status, version FROM loan_status WHERE loan_id = 'L0000099';",
                        verify_each_run=True,
                    ),
                    wrong=(
                        "INSERT INTO loan_status (loan_id, status, version) VALUES ('L0000099', 'active', 1);",
                        "INSERT INTO loan_status (loan_id, status, version) VALUES ('L0000099', 'open', 1) IF NOT EXISTS;",
                    ),
                    explain="The second time, [applied] is False and the row returned is the other writer's.",
                ),
                Exercise(
                    id="ch04.lock",
                    number="4.8",
                    title="Optimistic locking",
                    console="cql",
                    task="Close loan L0000006 in `loan_status` (status 'closed', version 2), but only if its version is still 1.",
                    starter="UPDATE loan_status SET status = 'closed', version = 2 WHERE loan_id = 'L0000006';",
                    hints=(
                        "An UPDATE can carry a condition on a column.",
                        "IF version = 1",
                        "A stale writer (version already 3) must change nothing.",
                    ),
                    solution="UPDATE loan_status SET status = 'closed', version = 2 WHERE loan_id = 'L0000006' IF version = 1;",
                    check=Verify(
                        setup="UPDATE loan_status SET status = 'active', version = 1 WHERE loan_id = 'L0000006';",
                        runs=2,
                        between="UPDATE loan_status SET status = 'active', version = 3 WHERE loan_id = 'L0000006';",
                        verify="SELECT loan_id, status, version FROM loan_status WHERE loan_id = 'L0000006';",
                        verify_each_run=True,
                    ),
                    wrong=(
                        "UPDATE loan_status SET status = 'closed', version = 2 WHERE loan_id = 'L0000006';",
                        "UPDATE loan_status SET status = 'closed', version = 2 WHERE loan_id = 'L0000006' IF version = 3;",
                    ),
                    explain="LWTs cost several round trips: use them for rare, important decisions, not every write.",
                ),
            ),
        ),
        Step(
            id="token-ranges",
            title="Extracting from Cassandra at scale",
            guide=GuideRef(4, "Extracting from Cassandra at scale"),
            prose=(
                "Every partition key hashes to a **token** between -2^63 and 2^63 - 1, and rows come back in token order. A scalable full extract splits the ring into contiguous ranges and reads each one: `WHERE token(loan_id) > ? AND token(loan_id) <= ?`.",
                "The lab split the ring into 16 equal ranges and read them on 8 threads: 11,465 rows, every row exactly once.",
            ),
            examples=(
                Example(
                    "Token order, not key order",
                    "cql",
                    "SELECT DISTINCT loan_id, token(loan_id) FROM payments_by_loan LIMIT 3;",
                ),
            ),
            exercises=(
                Exercise(
                    id="ch04.tokens",
                    number="4.9",
                    title="Read one token range",
                    console="cql",
                    task=(
                        "Split the ring into 16 equal ranges as the lab does: width = (2^63 - 1 - (-2^63)) // 16, the first range is "
                        "(-2^63, -2^63 + width]. Count the rows of `payments_by_loan` in that first range."
                    ),
                    starter="SELECT count(*) FROM payments_by_loan WHERE token(loan_id) > -9223372036854775808;",
                    hints=(
                        "-2^63 is -9223372036854775808; the width is 1152921504606846975.",
                        f"The first range ends at {FIRST_RANGE_END}.",
                        "Start exclusive (>), end inclusive (<=), so neighbouring ranges never overlap.",
                    ),
                    solution=f"SELECT count(*) FROM payments_by_loan\nWHERE token(loan_id) > -9223372036854775808 AND token(loan_id) <= {FIRST_RANGE_END};",
                    check=Match(by_position=True),
                    wrong=(
                        "SELECT count(*) FROM payments_by_loan WHERE token(loan_id) > -9223372036854775808 AND token(loan_id) <= 0;",
                        "SELECT count(*) FROM payments_by_loan;",
                    ),
                    explain="Each range is restartable on its own: record finished ranges, and a failed job resumes instead of starting over.",
                ),
            ),
        ),
    ),
)
