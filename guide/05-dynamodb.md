# 5. Amazon DynamoDB, with DynamoDB Local

Time: about 2 hours (45 minutes reading, 20 minutes lab, 50 minutes exercises).

In the lesson studio (`make up-05`, then `make studio`): chapter 05, 9 exercises in PartiQL or a JSON API mode that reports ConsumedCapacity.

```bash
make up-05      # DynamoDB Local 3.3.2 on localhost:8100, in memory
make lab-05
make check-05
make down
```

DynamoDB is a managed AWS service; this chapter runs **DynamoDB Local**, the
downloadable version AWS provides for development (`amazon/dynamodb-local:3.3.2`), with
`boto3` 1.44.6. No AWS account is used. DynamoDB Local behaves like the service for the
API calls in this chapter, with differences listed at the end. Read that list before
trusting a local result about scale, cost or timing.

## The model

A DynamoDB **table** holds **items** (rows). Each item is a set of **attributes**
(columns); apart from the key, items in one table need not share attributes. The
**primary key** is either

- a **partition key** alone, or
- a **partition key plus a sort key**. Items with the same partition key form an
  **item collection**, stored together and sorted by sort key.

That is the same idea as Cassandra's partition and clustering keys (chapter 4), offered
as a managed service. You read data three ways:

| Operation | SQL analogy | Cost |
|---|---|---|
| `GetItem` | `SELECT * WHERE pk = ? AND sk = ?` | one item |
| `Query` | `SELECT * WHERE pk = ? [AND sk BETWEEN ? AND ?] ORDER BY sk` | only the items in the key range |
| `Scan` | `SELECT * FROM table` (optionally filtered afterwards) | every item in the table |

Two more terms: an item may be at most 400 KB, and a `Query` or `Scan` returns at most
1 MB per call, with a `LastEvaluatedKey` to fetch the next page. Reads are eventually
consistent by default; `ConsistentRead=True` on a base-table read returns the latest
write, at twice the read cost.

## Start from the access patterns

The method is the one from chapter 4, made explicit: write down every access pattern,
then design keys so that each is a single `GetItem` or `Query`. Step 5.1 of
`make lab-05`:

```text
access pattern                            operation   key condition
----------------------------------------  ----------  --------------------------------------------------------
AP1 borrower profile                      GetItem     PK=BORROWER#<id>, SK=PROFILE
AP2 a borrower's applications and loans   Query       PK=BORROWER#<id>
AP3 a loan's payments in a date range     Query       PK=LOAN#<id>, SK BETWEEN PAYMENT#<from> AND PAYMENT#<to>
AP4 applications by status, newest first  Query GSI1  GSI1PK=STATUS#<status>, ScanIndexForward=false
AP5 loan details                          GetItem     PK=LOAN#<id>, SK=DETAILS
```

## Single-table design

**Single-table design** puts several entity types in one table, using generic key
names (`PK`, `SK`) and prefixed values (`BORROWER#B001532`, `APP#A0000006`). Items that are
read together share a partition key, so one `Query` returns a borrower's profile,
applications and loan references at once: a pre-joined item collection. Step 5.2 loads
the lender this way:

```text
BatchWriteItem: 18814 items in 4.9s
item type    items
-----------  ------
application  2393
borrower     2000
loan         1478
loan_ref     1478
payment      11,465
```

Payments use the sort key `PAYMENT#<ISO timestamp>#<event_id>`: ISO 8601 timestamps sort
correctly as strings, so a date range becomes a `BETWEEN` on the sort key, and the
event_id suffix keeps two payments at the same instant from colliding.

Single-table design is a means, not a goal. It pays off when access patterns are known
and stable and you want each screen served by one request. It costs flexibility: a new
question that does not fit the keys needs a new index or a backfill, and the raw table
is hard to read for anyone who did not design it. Several tables are fine when entities
are not read together.

## Global secondary indexes

A **global secondary index (GSI)** is a second copy of (some of) the table's items,
keyed differently, maintained by DynamoDB. AP4 needs applications by status, which is not
the table's key, so the application items also carry `GSI1PK = STATUS#<status>` and
`GSI1SK = <submitted_at>`. GSIs are updated asynchronously: reads from them are always
eventually consistent, and `ConsistentRead` is not allowed on them.

Each access pattern is one request (step 5.3). `ConsumedCapacity` is in **read capacity
units** (RCU): one RCU is one strongly consistent read of up to 4 KB, or two eventually
consistent ones; these numbers are as reported by DynamoDB Local:

```text
request                             Count  ScannedCount  ConsumedCapacity (RCU)
----------------------------------  -----  ------------  ----------------------
AP1 GetItem                         1      -             0.5
AP2 Query PK=BORROWER#B001532       5      5             0.5
AP3 Query LOAN#L0000006 Mar-Jun     4      4             0.5
AP4 Query GSI1 declined since June  117    117           2.5
```

## Scan with a filter reads everything

A `FilterExpression` is applied *after* items are read. You pay for, and wait for,
everything scanned. Step 5.4 asks the AP4 question with a `Scan`:

```text
Scan + FilterExpression: 3 pages (1 MB each at most), ScannedCount=18814, Count=117, ConsumedCapacity=305.0 RCU
the GSI1 query in 5.3 returned the same 117 items and read only those
```

Same 117 items: 2.5 RCU through the index, 305 RCU by scanning. This is DynamoDB's
`ALLOW FILTERING`. Compare `Count` with `ScannedCount` in any read you write; if they are
far apart, you are paying for a missing key design.

## Conditional writes

Every write can carry a `ConditionExpression`, checked atomically against the current
item. Two patterns cover most needs (step 5.5):

```text
write                                                    result
-------------------------------------------------------  -------------------------------
put #1 attribute_not_exists(PK)                          written
put #2 attribute_not_exists(PK)                          ConditionalCheckFailedException
writer A: SET status=closed IF version = 1               written
writer B (stale): SET status=written_off IF version = 1  ConditionalCheckFailedException
```

- **Insert if absent** (`attribute_not_exists(PK)`): idempotent creation, the DynamoDB
  version of the Redis `SET NX` and the Cassandra `IF NOT EXISTS`.
- **Optimistic locking** (`version = :expected` and `SET version = version + 1`): a
  writer that read an old version cannot overwrite a newer one.

## Transactions

`TransactWriteItems` applies up to 100 actions across items and tables, all or nothing.
Step 5.6 records a payment and adds it to the loan's paid total in one transaction, then
replays the same payment:

```text
payment + balance update: committed
same payment again:       TransactionCanceledException, reasons=['ConditionalCheckFailed', 'None']
paid_cents on the loan item = 65781 (counted once)
```

The condition on the payment item (`attribute_not_exists(SK)`) failed, so the balance
update in the same transaction was cancelled too. `CancellationReasons` lists one entry
per action, in order. A conditional insert plus a non-idempotent update, in one
transaction, is how you make "add to the total" safe against retries.

## DynamoDB Streams

A **DynamoDB Stream** is the table's change log: one record per item-level change, with
the old and/or new image of the item, kept for 24 hours. Records for one item appear in
the order of the changes. You read it shard by shard with a **shard iterator**;
`TRIM_HORIZON` starts at the oldest record still kept, and `AFTER_SEQUENCE_NUMBER` resumes
after a checkpoint, the way a MongoDB resume token does. DynamoDB Local supports
Streams; step 5.7:

```text
first read from TRIM_HORIZON (the oldest record still in the stream):
eventName  PK       old status  new status  SequenceNumber
---------  -------  ----------  ----------  ---------------------
INSERT     LOAN#L1  NULL        active      000000000000000144203
MODIFY     LOAN#L1  active      delinquent  000000000000000144204
INSERT     LOAN#L2  NULL        active      000000000000000144205
checkpoint saved: SequenceNumber 000000000000000144205
after 2 more writes, resume with AFTER_SEQUENCE_NUMBER=<checkpoint>:
eventName  PK       old status  new status  SequenceNumber
---------  -------  ----------  ----------  ---------------------
REMOVE     LOAN#L2  active      NULL        000000000000000144206
INSERT     LOAN#L3  NULL        active      000000000000000144207
```

(Sequence numbers differ between runs.) The delete arrives as a `REMOVE` with the old
image, so a CDC consumer sees deletes. In AWS you would usually let Lambda or the Kinesis
adapter manage shards and checkpoints; the 24-hour retention means a consumer that is down
longer than a day loses changes and must re-export.

## Time to live

TTL deletes items whose chosen attribute (a Unix timestamp in seconds) is in the past.
The service documents that expired items are typically deleted within a few days, and
until then they are still returned by reads. Step 5.8:

```text
TTL enabled on expires_at; item written already expired 60s ago; 2s later GetItem finds it: True
the same read with FilterExpression expires_at > now returns 0 items
```

If correctness depends on expiry, filter on it in every read. TTL deletions also appear
in the stream (on the service they are marked as deletions by the DynamoDB service
principal), so a CDC pipeline can tell expiry from a user delete.

## Export patterns

Ways to get a whole table out:

1. **Export to S3** (`ExportTableToPointInTime`): the service writes the table to S3 in
   DynamoDB JSON or Ion, without consuming read capacity. It needs point-in-time recovery
   enabled, and there is an incremental variant. This is the right choice on AWS, and it
   does not exist in DynamoDB Local:

   ```text
   ExportTableToPointInTime on DynamoDB Local -> UnknownOperationException
   ```

2. **Parallel scan**: `Scan` with `Segment=i, TotalSegments=n` from n workers, each
   following its own `LastEvaluatedKey`. It consumes read capacity, so throttle it on
   a busy table.
3. **Streams** for ongoing changes after an initial export.

Step 5.9 does the parallel scan and writes payments to Parquet:

```text
4 segments returned [4714, 4596, 4965, 4542] items = 18817 total, 18817 distinct keys, in 0.32s
wrote 11465 payment items to lake/ch05/payments.parquet; first months in DuckDB:
month    payments  amount
-------  --------  ----------
2025-02  173       114,961.91
2025-03  410       274,771.97
2025-04  625       410,923.34
2025-05  875       592,445.69
```

Note the four segments split the items with no overlap. The AWS usage notes for DynamoDB
Local say that parallel scans are not supported and that `Segment` and `TotalSegments`
are ignored; in this run, version 3.3.2 honoured them. Your export code should not
depend on either behaviour: the lab counts distinct keys, which would expose a local
version that returns the whole table in every segment.

## What DynamoDB Local does not emulate

From the AWS documentation for DynamoDB Local, plus what this lab observed:

- **Throughput and throttling.** Provisioned capacity is accepted and ignored; nothing
  is ever throttled; speed is your laptop's. Hot partitions and the service's per-partition
  limits cannot be reproduced locally.
- **Consistency.** Reads are documented as eventually consistent but, being local, almost
  always look strongly consistent. Code that is wrong under real eventual consistency
  will pass locally.
- **Parallel scan** is documented as unsupported (but see the observation above).
- **Transactions**: `TransactionConflictException` is never thrown locally.
- **Capacity numbers** in responses are computed locally; they were not compared with
  the service here.
- **Not available**: point-in-time recovery and therefore export to S3 (observed:
  `UnknownOperationException`), global tables, tagging, `billingModeSummary` (always
  null), item collection metrics.
- **TTL**: the setting is accepted; in this lab an expired item was still readable two
  seconds later, which is also allowed on the service. Whether DynamoDB Local ever
  deletes expired items was not tested.
- **Streams**: supported, but shard behaviour differs from the service.
- Table names are case-insensitive locally and case-sensitive on the service.

## Exercises

`exercises/ch05_dynamodb.py`:

1. `payments_between`: a `Query` with a sort-key range, end date inclusive (there is a
   trap in how ISO strings compare).
2. `put_if_absent`: a conditional put.
3. `set_status_if_version`: optimistic locking with a reserved word (`status`).
4. `export_items`: a parallel scan that follows pagination; the check's table is larger
   than one 1 MB page per segment.

```bash
make check-05
```

```text
Checking solutions/ch05_dynamodb.py
  PASS  5.1 payments_between: 4 payments for L0000006 between 2025-03-01 and 2025-06-30, end date inclusive
  PASS  5.2 put_if_absent: written once, second attempt rejected, original kept
  PASS  5.3 set_status_if_version: first writer applied (version 1 -> 2), stale writer rejected
  PASS  5.4 export_items: 11467 items, 4 segments, no duplicates, pagination followed

Chapter 5 (DynamoDB): 4/4 passed (checked solutions/ch05_dynamodb.py)
```

## What is not verified

- Nothing here ran against the DynamoDB service. Capacity, cost, latency, throttling and
  TTL deletion timing are as documented by AWS or as reported by DynamoDB Local.
- Export to S3, PITR and global tables are described from the documentation only.
- The parallel scan observation applies to DynamoDB Local 3.3.2 in this run; other
  versions may behave as the documentation says.

## Further reading

- [Core components](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.CoreComponents.html)
- [DynamoDB Local usage notes](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/DynamoDBLocal.UsageNotes.html)
- [Best practices for designing partition keys](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-partition-key-design.html)
- [Global secondary indexes](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/GSI.html)
- [Condition expressions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.ConditionExpressions.html)
  and [transactions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transactions.html)
- [Change data capture with DynamoDB Streams](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Streams.html)
- [Time to Live](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/TTL.html)
- [Export to S3](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/S3DataExport.HowItWorks.html)
