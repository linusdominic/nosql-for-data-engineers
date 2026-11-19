# 2. Document stores with MongoDB

Time: about 2 hours (45 minutes reading, 30 minutes lab, 45 minutes exercises).

```bash
make up-02      # MongoDB 8.0.38 as a single-node replica set, on localhost:27117
make lab-02
make check-02   # after the exercises
make down
```

Statements about MongoDB behaviour in this chapter apply to MongoDB 8.0, the pinned
version (`mongo:8.0.38`).

## Documents versus rows

A **document** is a JSON-like object stored as one unit. MongoDB stores it in a binary
format called BSON, which adds types JSON lacks (dates, 64-bit integers, decimals,
binary). Documents live in **collections**, which are the rough equivalent of tables,
inside a **database**. Every document has an `_id` field that is its primary key.

| Relational | MongoDB |
|---|---|
| database | database |
| table | collection |
| row | document |
| column | field (which may hold an object or an array) |
| primary key | `_id` (unique, always indexed) |
| `CREATE TABLE` with a schema | nothing: a collection accepts any document, unless you add validation |
| join | embed the related data, or `$lookup` in an aggregation |

The lab inserts the lender's 2,393 application documents. One of them, trimmed to one
uploaded document (`make lab-02`, step 2.1):

```json
{
  "_id": "A0000006",
  "application_id": "A0000006",
  "borrower": {
    "borrower_id": "B001532",
    "full_name": "Dalia Marrowby",
    "date_of_birth": "1980-01-18",
    "annual_income": 130500,
    "employment": { "status": "employed", "employer": "Quillfeather Joinery (fictional)", "years": 20 }
  },
  "contact": { "email": "dalia.marrowby1532@example.com", "phone": "+999 724380986" },
  "address": { "line1": "231 Bellfounder Yard", "town": "Fernmouth", "postcode": "ZZ4 2AB" },
  "device_id": "dev-2cf07801792b",
  "product": "home_improvement",
  "requested_amount": 47500.0,
  "term_months": 120,
  "channel": "mobile",
  "submitted_at": "2025-01-01T06:29:54+00:00",
  "documents": [ { "doc_type": "bank_statement", "uploaded_at": "2025-01-01T13:52:54+00:00", "verified": true } ],
  "schema_version": 1,
  "decision": { "score": 707, "outcome": "approved", "reasons": [], "decided_at": "2025-01-07T19:27:13+00:00" },
  "status": "funded",
  "updated_at": "2025-01-11T19:27:13+00:00",
  "loan": { "loan_id": "L0000006", "principal": 47500.0, "annual_rate": 0.1113, "term_months": 120,
            "instalment": 657.81, "originated_at": "2025-01-11T19:27:13+00:00" }
}
```

In a relational schema this one application would be rows in seven tables:
applications, borrowers, employment, documents, decisions, decline reasons, loans.
Here the application screen reads it with one lookup by `_id`.

Two details worth noticing, because they come back in the pipeline:

- `date_of_birth` is a string. BSON has a date-time type but no date-only type, so
  date-only values are often stored as strings (or as midnight UTC).
- Money is a BSON double here, as it often is in real systems. Doubles cannot represent
  most decimal fractions exactly. For new designs use `Decimal128` or integer minor units
  (cents); in the lake, this guide converts to `DECIMAL(12,2)`.

BSON dates have millisecond precision, and the maximum document size is 16 MB. Both
limits matter when you reconcile against a source that keeps microseconds, or when an
array grows without bound.

## Embed or reference?

**Embedding** puts related data inside the document (the borrower snapshot above).
**Referencing** stores only an id and looks the other document up when needed.

The lab stores the applications both ways and measures them (step 2.2):

```text
average document size, borrower embedded:   981 bytes
average document size, borrower referenced: 802 bytes
```

and joins the referenced version with `$lookup`, which is a left outer join:

```text
$lookup (a left outer join) from applications_ref to borrowers:
[ { "_id": "A0000006", "product": "home_improvement", "borrower": [ { "full_name": "Dalia Marrowby" } ] } ]
```

Rules of thumb:

- **Embed** what is read together and owned by the parent: an application's uploaded
  documents, its decision. Embedding also captures history: the borrower snapshot shows
  the income *at the time of the application*, which is what a credit model must use.
- **Reference** what is shared, large, or changes independently: the borrower's current
  profile, a product catalogue.
- **Never embed an array that grows without limit** (every payment of a loan, for
  example). The document approaches 16 MB and every update rewrites more data.

## Indexes and `explain()`

Without an index, MongoDB reads every document in the collection: a **collection scan**
(`COLLSCAN`), the equivalent of a full table scan. An index is a sorted structure on one
or more fields, exactly like a B-tree index in a relational database.

`explain("executionStats")` shows what the query planner chose and what it cost. The lab
asks for June's declined applications, sorted by submission time, before and after adding
a compound index (step 2.3):

```text
explain('executionStats')  no index          index {status:1, submitted_at:1}
-------------------------  ----------------  --------------------------------
stages                     SORT <- COLLSCAN  FETCH <- IXSCAN
nReturned                  117               117
totalKeysExamined          0                 117
totalDocsExamined          2393              117
```

Read it bottom-up: without the index, MongoDB scanned all 2,393 documents and then sorted
the 117 matches in memory. With the index, it walked 117 index keys (`IXSCAN`), fetched
exactly those 117 documents, and needed no sort because the index is already ordered by
`submitted_at` within each `status`. The SQL intuition carries over: equality fields
first, then the sort or range field.

An index on a field inside an array is a **multikey index**: it has one entry per array
element, so `{"documents.doc_type": "payslip"}` finds every application with a payslip
anywhere in its `documents` array:

```text
index on the array field documents.doc_type: stage=IXSCAN, isMultiKey=True
```

## The aggregation pipeline, mapped to SQL

An **aggregation pipeline** is a list of stages; each stage takes documents in and passes
documents on. Most stages have a direct SQL counterpart:

| Stage | SQL | What it does |
|---|---|---|
| `$match` | `WHERE` (or `HAVING` after a `$group`) | filter documents |
| `$group` | `GROUP BY` with aggregate functions | one output document per group key `_id` |
| `$project` / `$set` | the `SELECT` list | choose, rename or compute fields |
| `$sort`, `$limit`, `$skip` | `ORDER BY`, `LIMIT`, `OFFSET` | |
| `$lookup` | `LEFT OUTER JOIN` | adds an array of matching documents |
| `$unwind` | `CROSS JOIN LATERAL unnest(array)` | one document per array element |
| `$count` | `SELECT count(*)` | |

Approval rate by product (step 2.4); the comments in `src/nosqlde/labs/ch02_mongodb.py`
mark which SQL clause each stage replaces:

```python
[
    {"$match": {"status": {"$ne": "submitted"}}},                         # WHERE
    {"$group": {"_id": "$product",                                         # GROUP BY product
                "applications": {"$sum": 1},                               # COUNT(*)
                "approved": {"$sum": {"$cond": [{"$in": ["$status", ["approved", "funded"]]}, 1, 0]}},
                "avg_score": {"$avg": "$decision.score"}}},                # AVG(...)
    {"$project": {"applications": 1, "approved": 1,                        # SELECT ...
                  "approval_rate": {"$round": [{"$divide": ["$approved", "$applications"]}, 4]},
                  "avg_score": {"$round": ["$avg_score", 1]}}},
    {"$sort": {"_id": 1}},                                                 # ORDER BY
]
```

```text
product           applications  approved  approval_rate  avg_score
----------------  ------------  --------  -------------  ---------
auto              766           525       0.6854         666.6
home_improvement  826           536       0.6489         657.7
personal          801           545       0.6804         660.2
```

`$unwind` turns an array into rows, which is how you aggregate over embedded arrays:

```text
$unwind documents, then count unverified uploads per type:
doc_type        unverified
--------------  ----------
bank_statement  143
id_proof        160
payslip         147
utility_bill    149
```

## Schema validation

A collection accepts any document unless you attach a **validator**. `$jsonSchema`
describes required fields and their BSON types. With `validationAction: "error"`, a
document that does not match is rejected; with `"warn"` it is accepted and logged, which
is how you add validation to a collection that already holds bad data. Step 2.5 inserts a
normal application and one from the broker channel, which sends the amount as a string:

```text
insert A0000001 (requested_amount=28500.0): accepted
insert A0001143 (requested_amount='14000.00'): rejected, code 121, 'Document failed validation', operator 'properties'
```

Code 121 is `DocumentValidationFailure`. Validation runs on writes only: documents that
were in the collection before the validator was added stay as they are.

## Transactions

A single-document write is always atomic. MongoDB also supports multi-document
transactions (on replica sets since 4.0, on sharded clusters since 4.2), but never on a
standalone server, which is why
the compose file starts `mongod --replSet rs0` even though it is one node. Step 2.6
funds a loan: update the application and insert the loan, all or nothing. The first
attempt raises between the two writes:

```text
transaction 1 raised 'simulated crash between the two writes' and was aborted
  after abort:  application status='approved', loans=0
  after commit: application status='funded', loans=1
```

The status update from the failed attempt was rolled back. Use transactions sparingly:
the document model's answer to "these must change together" is usually "put them in one
document". By default a transaction that runs longer than 60 seconds is aborted
(`transactionLifetimeLimitSeconds`).

## The data engineering part

Everything so far is how an application uses MongoDB. The rest of the chapter is what
you will actually be asked to do: get the data out, into tables, every day.

### Flatten documents into tables

Analytics engines want flat, typed columns. The rules in `src/nosqlde/flatten.py`:

- nested objects become prefixed columns: `borrower.employment.status` becomes
  `borrower__employment__status`;
- arrays become **child tables** that carry the parent key and the element's position
  (`explode`), which is exactly a one-to-many table with a foreign key;
- an array you do not explode is kept as JSON text, so nothing is silently lost.

Step 2.7 splits every application into four tables:

```text
table                  rows
---------------------  ----
applications           2393
application_documents  5955
decline_reasons        1003
loans                  1478
```

### Find, conform and count schema drift

**Schema drift** is the gradual change of what a "schemaless" source actually contains.
The lab's data has three kinds, as real sources do. Step 2.8 first infers the types it
actually sees:

```text
columns with more than one type (column: {type: rows}):
  borrower__employment__employer: {'string': 1862, 'null': 421}
  requested_amount: {'float': 2187, 'string': 206}
```

Then it conforms every row to a fixed target schema with `drift.conform`, which never
guesses: it converts only when the conversion is unambiguous, sets NULL otherwise, keeps
unknown fields as JSON in a `_rescued` column, and counts everything:

```text
drift report for applications:
  rows: 2393
  missing     borrower__employment__employer: 110
  missing     borrower__employment__status: 110
  missing     borrower__employment__years: 110
  coerced     borrower__date_of_birth from string: 2393
  coerced     requested_amount from string: 206
  unexpected  marketing_consent: 835
```

How to read it:

- `missing ... 110`: 110 documents have no `employment` sub-document at all (one front
  end never sent it). That is different from the 421 retired borrowers whose employer is
  an explicit `null`: absent and null are not the same, and the report keeps them apart.
- `coerced ... date_of_birth: 2393`: every row. A coercion count equal to the row count
  is a *convention* of the source (dates stored as strings), not drift.
- `coerced requested_amount from string: 206`: a subset. That is drift: since
  1 April 2025 the broker channel sends `"14000.00"` instead of `14000.0`. Converting a
  numeric string to a decimal is unambiguous, so the value is kept.
- `unexpected marketing_consent: 835`: a field that appeared in May. It is not in the
  target schema yet, so it lands in `_rescued` (`{"marketing_consent": false}`) until
  someone decides to add a column. The capstone shows that next step.

A row that cannot be converted (say, `"n/a"` for an amount) is counted under `failed`.
A good pipeline alerts when `failed` is not zero, rather than quietly writing NULLs.

The conformed rows are written to Parquet and queried with DuckDB:

```text
product           loans  principal    avg_rate  with_rescued_fields
----------------  -----  -----------  --------  -------------------
auto              483    11025750.00  0.1166    181
home_improvement  501    16042750.00  0.1128    173
personal          494    6730500.00   0.1482    167
requested_amount type in Parquet: DECIMAL(12,2)
```

### Full versus incremental extraction with a watermark

A **full extract** reads everything every time. It is simple and always correct, and it
stops being affordable as the collection grows. An **incremental extract** reads only
what changed since the last run, using a **watermark**: the highest `updated_at` the
previous run saw. Step 2.9 runs it against a copy of the data as of 30 April, then applies
May's changes:

```text
run 1 (full):        1558 documents, watermark = 2025-04-30T23:01:15+00:00
source changes between runs: 438 inserted, 72 updated
run 2 (incremental): 510 documents, watermark = 2025-05-31T23:51:00+00:00
run 3 (no changes):  0 documents
hard-deleted ['A0001418', 'A0001497', 'A0001456']; run 4 sees 0 documents: a watermark query cannot see deletes
```

The watermark pattern relies on assumptions that you should check with the application
team, because each one breaks it:

1. **Every write sets `updated_at`.** One code path that forgets (a bulk fix in the shell,
   a migration) creates changes the extract never sees.
2. **`updated_at` comes from one clock and only moves forward.** Clocks on different
   application servers drift. Re-reading a small overlap (`>= watermark - 5 minutes`) and
   deduplicating by key downstream protects against small skews.
3. **A write is visible when it gets its timestamp.** A long transaction can commit a
   document with an `updated_at` older than a watermark already taken. The overlap helps
   here too.
4. **Nothing is hard-deleted.** Run 4 shows the blind spot. Either the application
   soft-deletes (`status: "deleted"`), or you periodically compare the set of keys (the
   capstone does this), or you use change streams.

Index the watermark field (`create_index("updated_at")`), or every incremental run is a
collection scan.

### Change data capture with change streams and resume tokens

**Change data capture (CDC)** means reading the database's own record of changes instead
of querying its current state. MongoDB records every write on a replica set in the
**oplog**, a capped collection on each member. A **change stream** is the supported API
on top of it: you `watch()` a collection, database or deployment and receive one event per
insert, update, replace or delete. Change streams need a replica set or sharded cluster;
on a standalone `mongod` they are not available.

Each event carries a **resume token**. Save the token after you have processed an event;
on restart, pass it as `resume_after` and the stream continues right after that event.
Step 2.10 does exactly this:

```text
consumer 1 read 5 events, saved the resume token, and stopped:
  insert  _id=X1
  insert  _id=X2
  update  _id=X1
  update  _id=X2
  delete  _id=X2
3 more changes happen while no consumer is running
consumer 2 started with resume_after=<saved token> and received:
  insert  _id=X3  fullDocument={'status': 'submitted'}
  update  _id=X1  fullDocument=None
  delete  _id=X1
```

Three lessons are in those lines:

- **Nothing was lost while the consumer was down**, and the delete arrived as an event.
  This is what watermark extraction cannot do.
- **`fullDocument=None` on the update.** With `full_document="updateLookup"`, MongoDB
  looks the document up *when the event is read*, not when the change happened. X1 had
  been deleted by then, so there was nothing to look up. If you need the document as it
  was at each change, enable pre- and post-images on the collection
  (`changeStreamPreAndPostImages`), then open the stream with
  `full_document="whenAvailable"` (or `"required"`) for the post-image and
  `full_document_before_change="whenAvailable"` for the pre-image. Or work from the
  update's `updateDescription`.
- **A resume token is only good while the oplog still holds it.** The oplog is a fixed
  size; if your consumer is down longer than the oplog window, resuming fails and you
  must re-snapshot. Monitor the window (`rs.printReplicationInfo()` in `mongosh`).

In production, resume tokens are usually stored next to the data they describe, written
only after that data is durable, exactly like the watermark in the capstone.

## Exercises

`exercises/ch02_mongodb.py` has four functions:

1. `explode_documents(app)`: turn the `documents` array into rows, without the helper.
2. `approval_rate_pipeline()`: an aggregation pipeline for approval rate by channel; the
   docstring gives the SQL to translate.
3. `extract_since(coll, watermark)`: incremental extraction that never moves the
   watermark backwards.
4. `read_changes_after(coll, token, expected)`: resume a change stream.

```bash
make check-02
```

When all four are right (output of `make check-02 SOLUTIONS=1`):

```text
Checking solutions/ch02_mongodb.py
  PASS  2.1 explode_documents: 5955 document rows from 2393 applications
  PASS  2.2 approval_rate_pipeline: branch=0.6667, broker=0.6793, mobile=0.6735, web=0.6667
  PASS  2.3 extract_since: full 1142, incremental 3, then 0; watermark never moved backwards
  PASS  2.4 read_changes_after: resumed and received insert, update, insert, delete in order

Chapter 2 (MongoDB): 4/4 passed (checked solutions/ch02_mongodb.py)
```

## What is not verified

- Resuming after the token has fallen off the oplog (`ChangeStreamHistoryLost`) is
  described, not demonstrated: the lab's oplog never rolls over.
- Resuming after a *server* restart is not shown; the lab restarts the consumer, not
  `mongod`. The resume mechanism is the same, but the lab does not prove it.
- Sharded clusters, read preferences on secondaries and write concerns other than the
  default were not exercised. Everything ran on one node.
- Timings (for example the insert time in step 2.1) are from one laptop and are not
  benchmarks.

## Further reading

- [Data modeling](https://www.mongodb.com/docs/v8.0/data-modeling/) and
  [embedding vs referencing](https://www.mongodb.com/docs/v8.0/data-modeling/concepts/embedding-vs-references/)
- [Explain results](https://www.mongodb.com/docs/v8.0/reference/explain-results/)
- [Aggregation pipeline stages](https://www.mongodb.com/docs/v8.0/reference/operator/aggregation-pipeline/)
  and the [SQL to aggregation mapping chart](https://www.mongodb.com/docs/v8.0/reference/sql-aggregation-comparison/)
- [Schema validation](https://www.mongodb.com/docs/v8.0/core/schema-validation/)
- [Transactions](https://www.mongodb.com/docs/v8.0/core/transactions/)
- [Change streams](https://www.mongodb.com/docs/v8.0/changeStreams/), including
  [resuming](https://www.mongodb.com/docs/v8.0/changeStreams/#resume-a-change-stream)
