# 4. Wide-column with Apache Cassandra

Time: about 2 hours (45 minutes reading, 20 minutes lab, 50 minutes exercises).

```bash
make up-04      # Cassandra 5.0.9 on localhost:9142; takes about a minute to become healthy
make lab-04
make check-04
make down
```

Statements in this chapter apply to Apache Cassandra 5.0 (`cassandra:5.0.9`) with the
image's default `cassandra.yaml`, and to the Python `cassandra-driver` 3.30.1.

## The model in one paragraph

Cassandra stores rows in tables, and you query them with CQL, which looks like SQL. The
difference is underneath. A table's primary key has two parts. The **partition key**
is hashed to a **token**, and the token decides which nodes store the row; all rows
with the same partition key form one **partition** and live together. The **clustering
key** sorts rows inside a partition on disk. A query is cheap when it names one
partition (and optionally a range of clustering keys); anything else means asking every
node to scan. There are no joins, and there is no query planner that will rescue a
table designed for different queries.

```sql
CREATE TABLE payments_by_loan (
    loan_id text, event_time timestamp, event_id uuid,
    event_day date, instalment_no int, amount_cents bigint, method text,
    PRIMARY KEY ((loan_id), event_time, event_id)       -- partition key, then clustering key
) WITH CLUSTERING ORDER BY (event_time DESC, event_id ASC);
```

| SQL idea | Cassandra |
|---|---|
| table | table, inside a **keyspace** (which also sets replication) |
| primary key | partition key + clustering columns; also the only thing you can filter on cheaply |
| index for each query | a separate table for each query, holding the same data with a different key |
| `INSERT` vs `UPDATE` | both are **upserts**: writing an existing key overwrites it, silently |
| `DELETE` | writes a **tombstone**, a marker that hides the data until compaction removes it |
| transaction | a compare-and-set on one partition with `IF` (LWT); a logged `BATCH` makes writes to several partitions all eventually apply, but without isolation |

The event_id in the clustering key matters: two payments of one loan with the same
`event_time` would otherwise have the same primary key, and the second write would
overwrite the first without any error. Exercise 4.1 checks you do not fall into this.

## Query-first modeling

In SQL you design entities and then write queries. In Cassandra you list the queries and
design one table per query. For payment events, three access patterns, three tables,
the same 11,465 rows in each (step 4.1 of `make lab-04`):

```text
CREATE TABLE payments_by_loan (... PRIMARY KEY ((loan_id), event_time, event_id))
CREATE TABLE payments_by_day (... PRIMARY KEY ((event_day), event_time, event_id))
CREATE TABLE payments_by_method (... PRIMARY KEY ((method), event_time, event_id))
inserted 11465 payment events into each of the 3 tables in 1.8s
```

The query "latest payments of a loan" reads one partition, already sorted (step 4.2):

```text
latest 3 payments of loan L0000006 (one partition, already sorted newest first):
event_time           instalment_no  amount_cents
-------------------  -------------  ------------
2025-12-13 19:55:53  11             65,781
2025-11-12 18:56:13  10             65,781
2025-10-10 17:57:08  9              65,781
```

A filter on a column that is not part of the key is refused outright:

```text
filter on a non-key column -> InvalidRequest: "Cannot execute this query as it might involve data filtering and thus may have unpredictable performance. If ...
```

## Why `ALLOW FILTERING` is a trap

The error message offers a way out: add `ALLOW FILTERING`. That tells Cassandra to scan
partitions and throw away the rows that do not match. Step 4.3 runs both queries with
**query tracing** on, which records what the server did:

```text
query                                        rows returned  query trace says
-------------------------------------------  -------------  -------------------------------------------------------------
WHERE loan_id = 'L0000006'                   11             Read 11 live rows and 0 tombstone cells
WHERE amount_cents > 215000 ALLOW FILTERING  75             Read 11465 live rows and 0 tombstone cells;
                                                            Submitting range requests on 17 ranges with a concurrency of 1 ...
```

To return 75 rows the filtered query read all 11,465, across every token range. On one
node with 11 thousand rows that takes milliseconds, which is exactly why it is a trap: it
passes in development and times out in production, where the same query reads every
partition on every node. Use `ALLOW FILTERING` only when the query is already restricted
to one partition. If you need the query, build a table for it, or answer it from the lake.

Cassandra 5.0 adds **Storage-Attached Indexes (SAI)**, secondary indexes that make some
non-key filters efficient. They are useful, but each query on them still contacts many
nodes; they do not replace query-first modelling for high-volume reads.

## Hot partitions and time bucketing

A partition is never split: all of it lives on the same replicas (RF of them). If one partition gets most of the
traffic or most of the data, those nodes do most of the work: a **hot partition**.
Step 4.4 counts rows per partition for the three designs:

```text
table               partition key  partitions  rows in largest  share of all rows
------------------  -------------  ----------  ---------------  -----------------
payments_by_method  method         3           6864             60%
payments_by_day     event_day      332         68               0.6%
payments_by_loan    loan_id        1465        11               0.10%
```

`payments_by_method` has three partitions; 60% of all payments sit in the
`direct_debit` partition, and it grows forever. With replication factor 3, three nodes
would hold it no matter how many nodes the cluster has. The usual fix is **bucketing**:
add a time bucket to the partition key, as `payments_by_day` does with `event_day`, or
`((method, event_day))` if the query really is by method. Pick the bucket so a partition
stays bounded; a common rule of thumb is to keep partitions well under 100 MB.

Bucketing by day has a second benefit you will use in the capstone: an incremental
extract can read "the last few days" as a handful of whole partitions.

## Tombstones

A delete in Cassandra does not remove data; it writes a **tombstone** that shadows it.
Tombstones are kept for `gc_grace_seconds` so that a replica that missed the delete
cannot bring the data back during repair, and are only dropped by compaction after that.
Every read has to step over the tombstones in its way. Step 4.5 uses a table as a work
queue, which is the classic mistake:

```text
inserted 2000 rows in one partition, then deleted 1500 of them one by one (a queue pattern)
SELECT the partition: 500 rows returned
server warning sent to the client: Read 500 live rows and 1500 tombstone cells (see tombstone_warn_threshold)
gc_grace_seconds = 864000 (10 days): tombstones stay at least this long
```

The thresholds come from this server's settings, printed at the top of the lab:
`tombstone_warn_threshold: 1000` and `tombstone_failure_threshold: 100000`. Past the
failure threshold the read is aborted. Patterns that create many tombstones: queues,
deleting and re-inserting, writing explicit NULLs (each one is a tombstone), and
collection columns that are overwritten. TTLs do not avoid tombstones: an expired cell
becomes one and waits out `gc_grace_seconds` like any other. What helps is data that
expires together: time-bucketed partitions with a table-level `default_time_to_live` and
`TimeWindowCompactionStrategy`, so whole SSTables expire and are dropped at once instead
of row-by-row deletes.

## Consistency levels

Each keyspace has a **replication factor** (RF): how many nodes keep a copy of each
partition. Each query has a **consistency level** (CL): how many of those replicas must
answer before the coordinator replies. Common levels:

| Level | Replicas that must answer (RF = 3) | Use |
|---|---|---|
| `ONE` / `LOCAL_ONE` | 1 | fastest; may read stale data |
| `QUORUM` / `LOCAL_QUORUM` | 2 (a majority: floor(RF/2) + 1) | the usual choice for both reads and writes |
| `ALL` | 3 | any replica down means failure |
| `SERIAL` / `LOCAL_SERIAL` | a Paxos majority | lightweight transactions |

If reads and writes together touch more replicas than RF (R + W > RF, for example
QUORUM + QUORUM with RF 3), every read overlaps the latest write. That is how Cassandra
gives you read-your-writes on top of eventual replication, per query, paying latency
for it: the PACELC trade-off from chapter 1. The Python driver's default consistency
level is `LOCAL_ONE`.

Step 4.6 shows the arithmetic on one node. A keyspace with RF 3 on a one-node cluster
cannot reach a quorum:

```text
keyspace  write consistency  result
--------  -----------------  --------------------------------------
RF=1      ONE                ok
RF=1      QUORUM             ok
RF=1      ALL                ok
RF=3      ONE                ok
RF=3      QUORUM             Unavailable: needs 2 replicas, 1 alive
RF=3      ALL                Unavailable: needs 3 replicas, 1 alive
```

## Lightweight transactions

A **lightweight transaction (LWT)** is a compare-and-set on one partition:
`INSERT ... IF NOT EXISTS`, or `UPDATE ... IF column = value`. It runs Paxos among the
replicas and is linearizable. The result has an `[applied]` column, and when the
condition fails it also returns the current row (step 4.7):

```text
statement                                 [applied]  returned
----------------------------------------  ---------  ---------------------------
INSERT ... IF NOT EXISTS                  True
INSERT ... IF NOT EXISTS (again)          False      existing row: status=active
UPDATE ... IF version = 1                 True
UPDATE ... IF version = 1 (stale writer)  False      current version=2
```

LWTs cost several round trips between replicas (this server runs `paxos_variant: v1`,
the 5.0.9 default; v2 needs fewer), so use them for rare, important decisions (claiming
an id, optimistic locking), not for every write. Mixing LWT and plain writes on the same
data loses the guarantee.

## Extracting from Cassandra at scale

A data engineer usually needs the whole table, not one partition. A plain
`SELECT * FROM payments_by_loan` works on a small table, but one coordinator then pages
through the entire cluster in one sequential stream. The scalable way is the one Spark's
Cassandra connector uses: split the **token ring** into ranges and read each range
separately, in parallel.

With the default partitioner (Murmur3), every partition key hashes to a token between
-2^63 and 2^63 - 1. Rows come back in token order, not key order:

```text
rows come back in token order, not loan_id order: L0000394 -> token -9218094246939253076, L0001928 -> token -9209753244238992445, L0001925 -> token -9209517730918558062
```

Step 4.8 splits the ring into 16 contiguous ranges and runs
`SELECT ... WHERE token(loan_id) > ? AND token(loan_id) <= ?` for each, on 8 threads,
writing one Parquet file per range:

```text
16 token ranges, 8 threads: 11465 rows in 0.06s; rows per range min=624 max=903
DuckDB over the extract: 11465 rows, 11465 distinct event_id, sum(amount_cents)=783269055
source events: 11465, sum(amount_cents)=783269055
```

Every row exactly once, and the sums agree. Points that matter in production:

- The ranges must be **contiguous and non-overlapping**: start just above -2^63 and end
  at 2^63 - 1, each `>` start and `<=` end. Exercise 4.2 makes you get this right.
- Use more ranges than nodes (and ideally align them with the nodes' own token ranges,
  from the driver's `cluster.metadata.token_map`) so that each query is served by its
  replicas. This server has 16 virtual nodes (`num_tokens: 16`), which is why the
  `ALLOW FILTERING` trace above mentioned 17 ranges.
- Each range query is restartable on its own: record finished ranges, and a failed job
  resumes instead of starting over.
- A token scan is a full read of the table and loads the cluster; run it at a
  consistency level and time of day agreed with the owners. For incremental extracts,
  model a table you can read incrementally (time-bucketed, like `payments_by_day`), or
  use Cassandra's CDC log feature, which this guide does not cover.

## Exercises

`exercises/ch04_cassandra.py`:

1. `payments_by_borrower_month_ddl()`: design a table for "a borrower's payments in a
   month, newest first". The check reads your table's key from `system_schema.columns`
   and also writes two payments with the same timestamp.
2. `token_ranges(n)`: split the ring with no gaps or overlaps.
3. `scan_by_token(...)`: read a whole table range by range.
4. `claim_payment(...)`: record a payment exactly once with an LWT.

```bash
make check-04
```

```text
Checking solutions/ch04_cassandra.py
  PASS  4.1 payments_by_borrower_month_ddl: partition (borrower_id, month), clustering event_time DESC, event_id
  PASS  4.2 token_ranges: contiguous, no gaps, no overlaps, for n = 1, 4, 7, 16
  PASS  4.3 scan_by_token: 1800 rows from 12 ranges, none missing, none duplicated
  PASS  4.4 claim_payment: first claim applied, second rejected, first writer's value kept

Chapter 4 (Cassandra): 4/4 passed (checked solutions/ch04_cassandra.py)
```

## What is not verified

- Everything runs on one node. Replica placement, repair, hinted handoff and the effect
  of consistency levels on stale reads across real replicas are explained, not shown;
  the RF 3 keyspace only demonstrates the "not enough replicas" failure.
- The "100 MB per partition" figure is a widely used rule of thumb, not something this
  lab measured.
- Paxos v2 was not tried; only the default (v1) ran.
- SAI indexes and Cassandra CDC are mentioned, not exercised.
- Timings are from one laptop and are not benchmarks.

## Further reading

- [Data modeling](https://cassandra.apache.org/doc/5.0/cassandra/developing/data-modeling/index.html)
- [Dynamo-style architecture: partitioning, replication, consistency](https://cassandra.apache.org/doc/5.0/cassandra/architecture/dynamo.html)
- [Compaction and tombstones](https://cassandra.apache.org/doc/5.0/cassandra/managing/operating/compaction/index.html)
- [CQL reference](https://cassandra.apache.org/doc/5.0/cassandra/developing/cql/index.html)
- [Storage-Attached Indexing](https://cassandra.apache.org/doc/5.0/cassandra/developing/cql/indexing/sai/sai-overview.html)
- [DataStax Python driver](https://docs.datastax.com/en/developer/python-driver/latest/)
