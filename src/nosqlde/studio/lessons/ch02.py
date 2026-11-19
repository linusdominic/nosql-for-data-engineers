"""Chapter 2 in the studio: MongoDB, in a mongosh-style console, plus DuckDB for the lake."""

from __future__ import annotations

from nosqlde.studio.checking import CheckRun, Outcome, failed, passed
from nosqlde.studio.lessons.model import Custom, Example, Exercise, GuideRef, Lesson, Match, Step, Verify
from nosqlde.studio.lessons.prepare import prepare_mongo
from nosqlde.studio.runners.base import RunResult

JUNE_DECLINED = '{status: "declined", submitted_at: {$gte: ISODate("2025-06-01")}}'


def _plan(answer: RunResult) -> dict[str, object] | None:
    last = answer.last
    if last is None or last.kind != "plan" or not isinstance(last.data, dict):
        return None
    summary = last.data.get("summary")
    return summary if isinstance(summary, dict) else None


def _count(run: CheckRun, query: str) -> int:
    value = run.last(f"db.applications.countDocuments({query})").data
    assert isinstance(value, int)
    return value


def _need_plan(answer: RunResult) -> tuple[dict[str, object] | None, Outcome | None]:
    plan = _plan(answer)
    if plan is None:
        return None, failed(
            "The last statement must be a find(...) ending in .explain('executionStats'), so the check can read the plan."
        )
    if plan.get("nReturned") is None:
        return None, failed(
            "Use the verbosity 'executionStats': .explain('executionStats') reports what the query read."
        )
    return plan, None


def check_collscan(run: CheckRun, answer: RunResult) -> Outcome:
    plan, bad = _need_plan(answer)
    if bad:
        return bad
    assert plan is not None
    want_n = _count(run, JUNE_DECLINED)
    total = _count(run, "{}")
    expected = {"stages": "SORT <- COLLSCAN", "nReturned": want_n, "totalDocsExamined": total}
    got = {k: plan.get(k) for k in ("stages", "nReturned", "totalDocsExamined")}
    if plan.get("nReturned") != want_n:
        return failed(
            f"Your query returned {plan.get('nReturned')} documents; June's declined applications are {want_n}. Check the filter.",
            expected,
            got,
        )
    if "COLLSCAN" not in str(plan.get("stages")):
        return failed(
            "The plan does not scan the collection. Did an index survive? The check drops them first; run exactly one find(...).explain(...).",
            expected,
            got,
        )
    return passed(
        f"COLLSCAN: MongoDB read all {plan.get('totalDocsExamined')} documents to return {want_n}, then sorted them in memory.",
        expected,
        got,
    )


def check_ixscan(run: CheckRun, answer: RunResult) -> Outcome:
    plan, bad = _need_plan(answer)
    if bad:
        return bad
    assert plan is not None
    want_n = _count(run, JUNE_DECLINED)
    expected = {
        "stages": "FETCH <- IXSCAN",
        "nReturned": want_n,
        "totalKeysExamined": want_n,
        "totalDocsExamined": want_n,
    }
    got = {
        k: plan.get(k) for k in ("stages", "nReturned", "totalKeysExamined", "totalDocsExamined", "indexName")
    }
    stages = str(plan.get("stages"))
    if plan.get("nReturned") != want_n:
        return failed(
            f"Your query returned {plan.get('nReturned')} documents, not {want_n}. Keep the same filter and sort.",
            expected,
            got,
        )
    if "IXSCAN" not in stages:
        return failed(
            "The plan is still a collection scan: create the index before the explain, in the same run.",
            expected,
            got,
        )
    if "SORT" in stages.split(" <- "):
        return failed(
            "The index is used for the filter, but MongoDB still sorts in memory (a SORT stage). Put the sort field in the index, after the equality field.",
            expected,
            got,
        )
    if plan.get("totalKeysExamined") != want_n:
        return failed(
            f"The index walked {plan.get('totalKeysExamined')} keys for {want_n} results. Equality fields first, then the range or sort field: {{status: 1, submitted_at: 1}}.",
            expected,
            got,
        )
    return passed(
        f"IXSCAN on {plan.get('indexName')}: {want_n} keys, {want_n} documents, no in-memory sort.",
        expected,
        got,
    )


def check_multikey(run: CheckRun, answer: RunResult) -> Outcome:
    plan, bad = _need_plan(answer)
    if bad:
        return bad
    assert plan is not None
    want_n = _count(run, '{"documents.doc_type": "payslip"}')
    expected = {"stages": "FETCH <- IXSCAN", "isMultiKey": True, "nReturned": want_n}
    got = {k: plan.get(k) for k in ("stages", "isMultiKey", "nReturned", "indexName")}
    if plan.get("nReturned") != want_n:
        return failed(
            f"Your query returned {plan.get('nReturned')} applications; {want_n} have a payslip.",
            expected,
            got,
        )
    if "IXSCAN" not in str(plan.get("stages")) or not plan.get("isMultiKey"):
        return failed(
            'The plan does not use a multikey index. Index the field inside the array: {"documents.doc_type": 1}.',
            expected,
            got,
        )
    return passed(
        f"A multikey index: one key per array element, {want_n} applications with a payslip.", expected, got
    )


LESSON = Lesson(
    id="ch02",
    number=2,
    title="Document stores with MongoDB",
    database="MongoDB 8.0",
    summary="Embed or reference, indexes and explain(), aggregation, validation, flattening into the lake, watermarks and change streams.",
    guide=GuideRef(2, "2. Document stores with MongoDB"),
    consoles=("mongo", "duckdb"),
    services=("mongo",),
    make_up="make up-02",
    prepare=prepare_mongo,
    prepare_note="Drops and reloads the database larkspur_studio (the lab's 2,393 applications and their variants) and writes lake/studio/ch02/.",
    steps=(
        Step(
            id="documents",
            title="Documents versus rows",
            guide=GuideRef(2, "Documents versus rows"),
            prose=(
                "A **document** is one JSON-like object stored as a unit, inside a **collection** (the rough equivalent of a table). Every document has an `_id`, its primary key.",
                "The console speaks a subset of `mongosh`: `db.<collection>.<method>(...)` with literal arguments. Unquoted keys, single quotes, `ISODate(...)` and `/regex/` all work, as they do at work.",
                "In a relational schema, one application would be rows in seven tables. Here the application screen reads it with one lookup by `_id`.",
            ),
            examples=(
                Example("List the collections", "mongo", "show collections"),
                Example("One application document", "mongo", 'db.applications.findOne({_id: "A0000006"})'),
                Example("How many documents", "mongo", "db.applications.countDocuments({})"),
            ),
        ),
        Step(
            id="embed",
            title="Embed or reference?",
            guide=GuideRef(2, "Embed or reference?"),
            prose=(
                "**Embedding** keeps related data inside the document: `applications` holds a snapshot of the borrower. **Referencing** stores only an id: `applications_ref` has a `borrower_id`, and the borrower lives in `borrowers`.",
                "The guide measured the cost: 981 bytes per document embedded, 802 referenced. The referenced version needs a `$lookup`, which is a left outer join, to show the borrower's name.",
            ),
            examples=(
                Example(
                    "Embedded: the borrower comes with the application",
                    "mongo",
                    'db.applications.findOne({_id: "A0000006"}, {product: 1, "borrower.full_name": 1, "borrower.annual_income": 1})',
                ),
                Example(
                    "Referenced: only an id",
                    "mongo",
                    'db.applications_ref.findOne({_id: "A0000006"}, {product: 1, borrower_id: 1})',
                ),
                Example(
                    "Average document size, both ways",
                    "mongo",
                    'db.applications.aggregate([{$group: {_id: null, avg_bytes: {$avg: {$bsonSize: "$$ROOT"}}}}])\n'
                    'db.applications_ref.aggregate([{$group: {_id: null, avg_bytes: {$avg: {$bsonSize: "$$ROOT"}}}}])',
                ),
            ),
            exercises=(
                Exercise(
                    id="ch02.lookup",
                    number="2.1",
                    title="Join a reference with $lookup",
                    console="mongo",
                    task=(
                        "From `applications_ref`, return application A0000006 with its `product` and the borrower's `full_name`, "
                        "looked up from `borrowers` (whose `_id` is the borrower id). Project `_id`, `product` and `borrower.full_name`, "
                        "with the looked-up array named `borrower`."
                    ),
                    starter='db.applications_ref.aggregate([\n  {$match: {_id: "A0000006"}},\n  // add a $lookup stage, then a $project\n])',
                    hints=(
                        "$lookup takes four fields: from, localField, foreignField and as.",
                        'The local field is borrower_id; the foreign field is _id in borrowers; name the result "borrower".',
                        'Finish with {$project: {_id: 1, product: 1, "borrower.full_name": 1}}.',
                    ),
                    solution=(
                        "db.applications_ref.aggregate([\n"
                        '  {$match: {_id: "A0000006"}},\n'
                        '  {$lookup: {from: "borrowers", localField: "borrower_id", foreignField: "_id", as: "borrower"}},\n'
                        '  {$project: {_id: 1, product: 1, "borrower.full_name": 1}}\n'
                        "])"
                    ),
                    check=Match(fields=("_id", "product", "borrower.0.full_name")),
                    wrong=(
                        'db.applications_ref.aggregate([{$match: {_id: "A0000006"}}, {$lookup: {from: "borrowers", localField: "_id", foreignField: "_id", as: "borrower"}}])',
                        'db.applications_ref.aggregate([{$match: {_id: "A0000007"}}, {$lookup: {from: "borrowers", localField: "borrower_id", foreignField: "_id", as: "borrower"}}])',
                    ),
                    explain="$lookup is a left outer join: an application whose borrower is missing still comes back, with an empty array.",
                ),
            ),
        ),
        Step(
            id="indexes",
            title="Indexes and explain()",
            guide=GuideRef(2, "Indexes and `explain()`"),
            prose=(
                "Without an index, MongoDB reads every document: a **collection scan** (`COLLSCAN`). An index is a sorted B-tree on one or more fields, as in SQL.",
                "`explain('executionStats')` shows the plan the server chose and what it read: `nReturned`, `totalKeysExamined` and `totalDocsExamined`. Read the stages from right to left: `SORT <- COLLSCAN` means scan, then sort in memory.",
                "Each check below drops the collection's indexes first, so every exercise starts from the same plan.",
            ),
            examples=(
                Example("The indexes on applications", "mongo", "db.applications.getIndexes()"),
                Example("Drop every index except _id", "mongo", "db.applications.dropIndexes()"),
            ),
            exercises=(
                Exercise(
                    id="ch02.collscan",
                    number="2.2",
                    title="See a collection scan",
                    console="mongo",
                    task=(
                        'Explain June\'s declined applications, sorted by submission time, with no index: find `status` "declined" and '
                        "`submitted_at` on or after 1 June 2025, sort by `submitted_at` ascending, and end with `.explain('executionStats')`."
                    ),
                    starter=f"db.applications.find({JUNE_DECLINED})",
                    hints=(
                        "Chain .sort({submitted_at: 1}) after the find.",
                        "Finish the chain with .explain('executionStats').",
                        "Look at totalDocsExamined: how does it compare with nReturned?",
                    ),
                    solution=f'db.applications.find({JUNE_DECLINED}).sort({{submitted_at: 1}}).explain("executionStats")',
                    check=Custom(
                        check_collscan,
                        setup="db.applications.dropIndexes()",
                        description="COLLSCAN reading every document",
                    ),
                    wrong=(
                        f"db.applications.find({JUNE_DECLINED}).sort({{submitted_at: 1}})",
                        'db.applications.find({status: "approved", submitted_at: {$gte: ISODate("2025-06-01")}}).sort({submitted_at: 1}).explain("executionStats")',
                    ),
                    explain="2,393 documents read and sorted in memory to return 117: the SQL full table scan.",
                ),
                Exercise(
                    id="ch02.ixscan",
                    number="2.3",
                    title="Make it an index scan",
                    console="mongo",
                    task=(
                        "Create a compound index that serves both the filter and the sort of exercise 2.2, then run the same explain. "
                        "The check wants an `IXSCAN`, no in-memory `SORT`, and as many keys examined as documents returned."
                    ),
                    starter=f'// create the index here\ndb.applications.find({JUNE_DECLINED}).sort({{submitted_at: 1}}).explain("executionStats")',
                    hints=(
                        "db.applications.createIndex({...}) on two fields.",
                        "Equality field first, then the range and sort field.",
                        "db.applications.createIndex({status: 1, submitted_at: 1})",
                    ),
                    solution=(
                        "db.applications.createIndex({status: 1, submitted_at: 1})\n"
                        f'db.applications.find({JUNE_DECLINED}).sort({{submitted_at: 1}}).explain("executionStats")'
                    ),
                    check=Custom(check_ixscan, setup="db.applications.dropIndexes()"),
                    wrong=(
                        "db.applications.createIndex({submitted_at: 1, status: 1})\n"
                        f'db.applications.find({JUNE_DECLINED}).sort({{submitted_at: 1}}).explain("executionStats")',
                        "db.applications.createIndex({status: 1})\n"
                        f'db.applications.find({JUNE_DECLINED}).sort({{submitted_at: 1}}).explain("executionStats")',
                    ),
                    explain="The index is ordered by submitted_at within each status, so MongoDB walks exactly the 117 keys, already sorted.",
                ),
                Exercise(
                    id="ch02.multikey",
                    number="2.4",
                    title="Index a field inside an array",
                    console="mongo",
                    task=(
                        "Applications have an array `documents` of uploads, each with a `doc_type`. Create an index that lets "
                        "MongoDB find every application with a payslip without scanning, then explain "
                        '`find({"documents.doc_type": "payslip"})` with executionStats.'
                    ),
                    starter='db.applications.find({"documents.doc_type": "payslip"}).explain("executionStats")',
                    hints=(
                        "Index the dotted path into the array.",
                        'db.applications.createIndex({"documents.doc_type": 1})',
                        "In the plan, look for isMultiKey: true.",
                    ),
                    solution=(
                        'db.applications.createIndex({"documents.doc_type": 1})\n'
                        'db.applications.find({"documents.doc_type": "payslip"}).explain("executionStats")'
                    ),
                    check=Custom(check_multikey, setup="db.applications.dropIndexes()"),
                    wrong=(
                        'db.applications.find({"documents.doc_type": "payslip"}).explain("executionStats")',
                        'db.applications.createIndex({documents: 1})\ndb.applications.find({"documents.doc_type": "payslip"}).explain("executionStats")',
                    ),
                    explain="A multikey index has one entry per array element, so an application with three uploads has three keys.",
                ),
            ),
        ),
        Step(
            id="aggregation",
            title="The aggregation pipeline, mapped to SQL",
            guide=GuideRef(2, "The aggregation pipeline, mapped to SQL"),
            prose=(
                "A pipeline is a list of stages: `$match` is `WHERE`, `$group` is `GROUP BY`, `$project` and `$set` are the `SELECT` list, `$sort` is `ORDER BY`, `$unwind` is `CROSS JOIN LATERAL unnest(...)`.",
                'In `$group`, the `_id` is the group key and every other field is an aggregate such as `{$sum: 1}` (count) or `{$avg: "$decision.score"}`.',
            ),
            examples=(
                Example(
                    "Applications per status",
                    "mongo",
                    'db.applications.aggregate([\n  {$group: {_id: "$status", n: {$sum: 1}}},\n  {$sort: {n: -1}}\n])',
                ),
                Example("The channels", "mongo", 'db.applications.distinct("channel")'),
            ),
            exercises=(
                Exercise(
                    id="ch02.approval",
                    number="2.5",
                    title="Approval rate by product",
                    console="mongo",
                    task=(
                        "Ignore applications still `submitted`. For each `product`, return `_id` (the product), `applications` (count), "
                        "`approved` (status `approved` or `funded`) and `approval_rate` (approved / applications, rounded to 4 decimals), "
                        "sorted by `_id`."
                    ),
                    starter='db.applications.aggregate([\n  {$match: {status: {$ne: "submitted"}}},\n  // $group, then the rate, then $sort\n])',
                    hints=(
                        '{$group: {_id: "$product", applications: {$sum: 1}, approved: {$sum: ...}}}',
                        'Count approved with {$sum: {$cond: [{$in: ["$status", ["approved", "funded"]]}, 1, 0]}}.',
                        'Then {$set: {approval_rate: {$round: [{$divide: ["$approved", "$applications"]}, 4]}}} and {$sort: {_id: 1}}.',
                    ),
                    solution=(
                        "db.applications.aggregate([\n"
                        '  {$match: {status: {$ne: "submitted"}}},\n'
                        '  {$group: {_id: "$product", applications: {$sum: 1},\n'
                        '            approved: {$sum: {$cond: [{$in: ["$status", ["approved", "funded"]]}, 1, 0]}}}},\n'
                        '  {$set: {approval_rate: {$round: [{$divide: ["$approved", "$applications"]}, 4]}}},\n'
                        "  {$sort: {_id: 1}}\n"
                        "])"
                    ),
                    check=Match(fields=("_id", "applications", "approved", "approval_rate"), ordered=True),
                    wrong=(
                        'db.applications.aggregate([{$match: {status: {$ne: "submitted"}}}, {$group: {_id: "$channel", applications: {$sum: 1}, approved: {$sum: {$cond: [{$in: ["$status", ["approved", "funded"]]}, 1, 0]}}}}, {$set: {approval_rate: {$round: [{$divide: ["$approved", "$applications"]}, 4]}}}, {$sort: {_id: 1}}])',
                        'db.applications.aggregate([{$match: {status: {$ne: "submitted"}}}, {$group: {_id: "$product", applications: {$sum: 1}, approved: {$sum: {$cond: [{$eq: ["$status", "approved"]}, 1, 0]}}}}, {$set: {approval_rate: {$round: [{$divide: ["$approved", "$applications"]}, 4]}}}, {$sort: {_id: 1}}])',
                    ),
                    explain="auto 766 / 525 / 0.6854 is the guide's step 2.4 table.",
                ),
                Exercise(
                    id="ch02.unwind",
                    number="2.6",
                    title="Aggregate over an embedded array",
                    console="mongo",
                    task=(
                        "Count the unverified uploads per document type: one row per `documents.doc_type` with `_id` (the type) and "
                        "`unverified` (how many uploads of that type have `verified: false`), sorted by `_id`."
                    ),
                    starter="db.applications.aggregate([\n  // one document per upload first\n])",
                    hints=(
                        'Start with {$unwind: "$documents"}: one document per array element.',
                        'Then {$match: {"documents.verified": false}}.',
                        'Group on "$documents.doc_type" with {$sum: 1}, then sort.',
                    ),
                    solution=(
                        "db.applications.aggregate([\n"
                        '  {$unwind: "$documents"},\n'
                        '  {$match: {"documents.verified": false}},\n'
                        '  {$group: {_id: "$documents.doc_type", unverified: {$sum: 1}}},\n'
                        "  {$sort: {_id: 1}}\n"
                        "])"
                    ),
                    check=Match(fields=("_id", "unverified"), ordered=True),
                    wrong=(
                        'db.applications.aggregate([{$match: {"documents.verified": false}}, {$group: {_id: "$documents.doc_type", unverified: {$sum: 1}}}, {$sort: {_id: 1}}])',
                        'db.applications.aggregate([{$unwind: "$documents"}, {$group: {_id: "$documents.doc_type", unverified: {$sum: 1}}}, {$sort: {_id: 1}}])',
                    ),
                    explain="Without $unwind, $match keeps whole applications with at least one unverified upload, and the group key is an array.",
                ),
            ),
        ),
        Step(
            id="validation",
            title="Schema validation",
            guide=GuideRef(2, "Schema validation"),
            prose=(
                "A collection accepts any document unless it has a **validator**. `applications_validated` has the lab's `$jsonSchema`: "
                "`application_id` must be a string, `requested_amount` a number, `status` one of five values.",
                'Since 1 April 2025 the broker channel sends amounts as strings such as `"14000.00"`. With `validationAction: "error"` such a document is rejected with code 121, `DocumentValidationFailure`.',
            ),
            examples=(
                Example(
                    "Try the broker's document as it arrives",
                    "mongo",
                    'db.applications_validated.insertOne({_id: "A0001143", application_id: "A0001143", requested_amount: "14000.00", status: "submitted"})',
                    note="Rejected: read the 'Additional information' to see which rule failed.",
                ),
            ),
            exercises=(
                Exercise(
                    id="ch02.validation",
                    number="2.7",
                    title="Get past the validator",
                    console="mongo",
                    task=(
                        "Insert application A0001143 into `applications_validated` so that the validator accepts it: `_id` and "
                        '`application_id` "A0001143", `status` "submitted", and the broker\'s amount 14000.00 stored as a number, not a string.'
                    ),
                    starter='db.applications_validated.insertOne({_id: "A0001143", application_id: "A0001143", requested_amount: "14000.00", status: "submitted"})',
                    hints=(
                        "The validator wants requested_amount with bsonType double, int, long or decimal.",
                        "Drop the quotes around the number, or use NumberDecimal('14000.00').",
                        "Run the example first if you want to see the rejection.",
                    ),
                    solution='db.applications_validated.insertOne({_id: "A0001143", application_id: "A0001143", requested_amount: 14000.00, status: "submitted"})',
                    check=Verify(
                        setup="db.applications_validated.deleteMany({})",
                        verify="db.applications_validated.find({}, {application_id: 1, requested_amount: 1, status: 1})",
                    ),
                    wrong=(
                        'db.applications_validated.insertOne({_id: "A0001143", application_id: "A0001143", requested_amount: "14000.00", status: "submitted"})',
                        'db.applications_validated.insertOne({_id: "A0001143", application_id: "A0001143", requested_amount: 14000.00, status: "pending"})',
                    ),
                    explain="Validation runs on writes only: documents stored before the validator was added stay as they were.",
                ),
            ),
        ),
        Step(
            id="flatten",
            title="Flatten documents into tables",
            guide=GuideRef(2, "Flatten documents into tables"),
            prose=(
                "Prepare flattened every application into four tables with the lab's code and wrote them to `lake/studio/ch02/`: "
                "nested objects became prefixed columns (`borrower__employment__status`), arrays became child tables, and fields "
                "outside the target schema landed as JSON in `_rescued`.",
                "Switch the console to **DuckDB** to query them with SQL. Paths are relative to the repository root.",
            ),
            examples=(
                Example(
                    "The columns of the flattened table",
                    "duckdb",
                    "DESCRIBE SELECT * FROM 'lake/studio/ch02/applications.parquet'",
                ),
                Example(
                    "What landed in _rescued",
                    "duckdb",
                    "SELECT _rescued, count(*) AS rows\nFROM 'lake/studio/ch02/applications.parquet'\nGROUP BY ALL ORDER BY rows DESC",
                ),
            ),
            exercises=(
                Exercise(
                    id="ch02.lake",
                    number="2.8",
                    title="Query the flattened tables",
                    console="duckdb",
                    task=(
                        "Join `loans.parquet` to `applications.parquet` (both in `lake/studio/ch02/`) on `application_id`. Per `product`, "
                        "return `product`, `loans` (count) and `with_rescued_fields` (loans whose application has a non-null `_rescued`), sorted by product."
                    ),
                    starter="SELECT a.product, count(*) AS loans\nFROM 'lake/studio/ch02/loans.parquet' l\nJOIN 'lake/studio/ch02/applications.parquet' a USING (application_id)\nGROUP BY a.product ORDER BY a.product",
                    hints=(
                        "Add a filtered count: count(*) FILTER (WHERE a._rescued IS NOT NULL).",
                        "Alias it AS with_rescued_fields.",
                        "Keep the GROUP BY and ORDER BY on a.product.",
                    ),
                    solution=(
                        "SELECT a.product,\n"
                        "       count(*) AS loans,\n"
                        "       count(*) FILTER (WHERE a._rescued IS NOT NULL) AS with_rescued_fields\n"
                        "FROM 'lake/studio/ch02/loans.parquet' l\n"
                        "JOIN 'lake/studio/ch02/applications.parquet' a USING (application_id)\n"
                        "GROUP BY a.product ORDER BY a.product"
                    ),
                    check=Match(fields=("product", "loans", "with_rescued_fields"), ordered=True),
                    wrong=(
                        "SELECT product, count(*) AS loans, count(*) FILTER (WHERE _rescued IS NOT NULL) AS with_rescued_fields FROM 'lake/studio/ch02/applications.parquet' GROUP BY product ORDER BY product",
                        "SELECT a.product, count(*) AS loans, count(*) FILTER (WHERE a._rescued IS NULL) AS with_rescued_fields FROM 'lake/studio/ch02/loans.parquet' l JOIN 'lake/studio/ch02/applications.parquet' a USING (application_id) GROUP BY a.product ORDER BY a.product",
                    ),
                    explain="483, 501 and 494 loans, as in the guide's step 2.8; 181, 173 and 167 of them carry marketing_consent, the field that appeared in May.",
                ),
            ),
        ),
        Step(
            id="watermark",
            title="Full versus incremental extraction with a watermark",
            guide=GuideRef(2, "Full versus incremental extraction with a watermark"),
            prose=(
                "An incremental extract reads only what changed since the last run, using a **watermark**: the highest `updated_at` the previous run saw.",
                "`applications_inc` is the lab's copy: 1,558 documents as of 30 April, then May's changes (438 inserted, 72 updated). Run 1 ended with the watermark `2025-04-30T23:01:15Z`. The collection has an index on `updated_at`, or every run would be a collection scan.",
            ),
            examples=(
                Example(
                    "The highest updated_at right now",
                    "mongo",
                    "db.applications_inc.find({}, {_id: 1, updated_at: 1}).sort({updated_at: -1}).limit(1)",
                ),
                Example("The index on the watermark field", "mongo", "db.applications_inc.getIndexes()"),
            ),
            exercises=(
                Exercise(
                    id="ch02.watermark",
                    number="2.9",
                    title="Run 2 of an incremental extract",
                    console="mongo",
                    task=(
                        "Return every document in `applications_inc` changed after the watermark 2025-04-30T23:01:15Z, with only `_id` and "
                        "`updated_at`, sorted by `updated_at` then `_id` (so the next watermark is the last row)."
                    ),
                    starter="db.applications_inc.find({updated_at: {}}, {_id: 1, updated_at: 1})",
                    hints=(
                        'Strictly after: {$gt: ISODate("2025-04-30T23:01:15Z")}.',
                        "Why not $gte? The document at exactly the watermark was already extracted by run 1.",
                        ".sort({updated_at: 1, _id: 1}) gives a deterministic order.",
                    ),
                    solution='db.applications_inc.find({updated_at: {$gt: ISODate("2025-04-30T23:01:15Z")}}, {_id: 1, updated_at: 1}).sort({updated_at: 1, _id: 1})',
                    check=Match(fields=("_id", "updated_at"), ordered=True),
                    wrong=(
                        'db.applications_inc.find({updated_at: {$gte: ISODate("2025-04-30T23:01:15Z")}}, {_id: 1, updated_at: 1}).sort({updated_at: 1, _id: 1})',
                        'db.applications_inc.find({updated_at: {$gt: ISODate("2025-04-30T23:01:15Z")}}, {_id: 1, updated_at: 1}).sort({_id: 1})',
                    ),
                    explain="510 documents: the 438 inserts and 72 updates, as in the guide. A hard delete would never show up here.",
                ),
            ),
        ),
        Step(
            id="cdc",
            title="Change data capture with change streams",
            guide=GuideRef(2, "Change data capture with change streams and resume tokens"),
            prose=(
                "A **change stream** reads the oplog through a supported API: one event per insert, update, replace or delete, each with a **resume token**.",
                "A console cannot hold a stream open, so prepare ran the lab's step 2.10 and stored the 8 events it read in `cdc_events`: 5 by consumer 1, then 3 more by consumer 2 after it resumed from the saved token.",
            ),
            examples=(
                Example(
                    "Every captured event",
                    "mongo",
                    "db.cdc_events.find({}, {consumer: 1, operationType: 1, documentKey: 1, fullDocument: 1}).sort({_id: 1})",
                ),
            ),
            exercises=(
                Exercise(
                    id="ch02.cdc",
                    number="2.10",
                    title="Find what a watermark cannot see",
                    console="mongo",
                    task=(
                        "From `cdc_events`, return the `documentKey` of every delete event, in the order they arrived (`_id` ascending), "
                        "and nothing else (exclude `_id`)."
                    ),
                    starter="db.cdc_events.find({}, {})",
                    hints=(
                        'Filter on {operationType: "delete"}.',
                        "Project {_id: 0, documentKey: 1}.",
                        "Sort with .sort({_id: 1}).",
                    ),
                    solution='db.cdc_events.find({operationType: "delete"}, {_id: 0, documentKey: 1}).sort({_id: 1})',
                    check=Match(fields=("documentKey._id",), ordered=True, extra_ok=False),
                    wrong=(
                        'db.cdc_events.find({operationType: "update"}, {_id: 0, documentKey: 1}).sort({_id: 1})',
                        'db.cdc_events.find({operationType: "delete"}, {documentKey: 1}).sort({_id: 1})',
                    ),
                    explain="X2, then X1: the stream delivered both deletes, including the one that happened while no consumer was running.",
                ),
            ),
        ),
    ),
)
