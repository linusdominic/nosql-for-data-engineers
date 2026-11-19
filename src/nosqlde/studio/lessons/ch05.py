"""Chapter 5 in the studio: DynamoDB Local, in PartiQL and in a JSON API mode."""

from __future__ import annotations

import json
from typing import Any

from nosqlde.studio.checking import CheckRun, Outcome, failed, passed
from nosqlde.studio.compare import compare, records
from nosqlde.studio.lessons.model import Custom, Example, Exercise, GuideRef, Lesson, Match, Step, Verify
from nosqlde.studio.lessons.prepare import prepare_dynamodb
from nosqlde.studio.runners.base import RunResult

T = "larkspur_studio"

GSI_QUERY = json.dumps(
    {
        "op": "Query",
        "TableName": T,
        "IndexName": "GSI1",
        "KeyConditionExpression": "GSI1PK = :s AND GSI1SK >= :from",
        "ExpressionAttributeValues": {":s": {"S": "STATUS#declined"}, ":from": {"S": "2025-06-01"}},
        "ScanIndexForward": False,
    },
    indent=2,
)
SCAN_QUERY = json.dumps(
    {
        "op": "Scan",
        "TableName": T,
        "FilterExpression": "GSI1PK = :s AND GSI1SK >= :from",
        "ExpressionAttributeValues": {":s": {"S": "STATUS#declined"}, ":from": {"S": "2025-06-01"}},
    },
    indent=2,
)
PAYMENT_SK = "PAYMENT#2026-01-05T09:00:00+00:00#demo"
LOAN_KEY = {"PK": {"S": "LOAN#L0000006"}, "SK": {"S": "DETAILS"}}


def _j(value: Any) -> str:
    return json.dumps(value, indent=2)


def _declined_since_june(run: CheckRun) -> list[dict[str, Any]]:
    return records(run.last(GSI_QUERY))


def _read_stats(answer: RunResult) -> dict[str, Any] | None:
    last = answer.last
    if last is None or not isinstance(last.data, dict) or "scanned" not in last.data:
        return None
    return last.data


def check_gsi(run: CheckRun, answer: RunResult) -> Outcome:
    stats = _read_stats(answer)
    if stats is None:
        return failed(
            'Use the JSON mode ({"op": "Query", ...}) so the console can show Count, ScannedCount and ConsumedCapacity.'
        )
    want = _declined_since_june(run)
    c = compare(want, records(answer.last) if answer.last else [], fields=("PK", "SK"))
    expected = {"Count": len(want), "ScannedCount": len(want)}
    got = {"Count": stats["count"], "ScannedCount": stats["scanned"], "ConsumedCapacity": stats["capacity"]}
    if not c.ok:
        return failed("Not the declined applications submitted since 1 June. " + c.message, expected, got)
    if stats["scanned"] != stats["count"]:
        return failed(
            f"The right {stats['count']} items, but DynamoDB read {stats['scanned']} to find them ({stats['capacity']:g} RCU). Query the index instead of filtering.",
            expected,
            got,
        )
    return passed(
        f"{stats['count']} items, {stats['scanned']} read, {stats['capacity']:g} RCU: the index holds exactly these items.",
        expected,
        got,
    )


def check_scan(run: CheckRun, answer: RunResult) -> Outcome:
    stats = _read_stats(answer)
    if stats is None:
        return failed(
            'Use the JSON mode with "op": "Scan" so the console shows ScannedCount and ConsumedCapacity.'
        )
    total = run.last(_j({"op": "Scan", "TableName": T, "Select": "COUNT"})).data
    assert isinstance(total, dict)
    want = _declined_since_june(run)
    c = compare(want, records(answer.last) if answer.last else [], fields=("PK", "SK"))
    expected = {"Count": len(want), "ScannedCount": total["count"]}
    got = {
        "Count": stats["count"],
        "ScannedCount": stats["scanned"],
        "ConsumedCapacity": stats["capacity"],
        "pages": stats["pages"],
    }
    if stats["scanned"] != total["count"]:
        if stats["scanned"] == stats["count"]:
            return failed(
                "That reads only the matching items: this exercise is about measuring a Scan with a FilterExpression.",
                expected,
                got,
            )
        return failed(
            f"The scan read {stats['scanned']} of {total['count']} items: it stopped at a page boundary. Follow LastEvaluatedKey (leave paginate on).",
            expected,
            got,
        )
    if not c.ok:
        return failed(
            "The scan read everything, but the filter does not return June's declined applications. "
            + c.message,
            expected,
            got,
        )
    return passed(
        f"{stats['scanned']} items read over {stats['pages']} pages to return {stats['count']}: {stats['capacity']:g} RCU, against 2.5 through the index.",
        expected,
        got,
    )


def check_transaction(run: CheckRun, answer: RunResult) -> Outcome:
    try:
        requests = json.loads(run.answer)
    except json.JSONDecodeError:
        requests = None
    ops = [
        r.get("op") for r in (requests if isinstance(requests, list) else [requests]) if isinstance(r, dict)
    ]
    if not ops or any(op not in ("TransactWriteItems", "ExecuteTransaction") for op in ops):
        return failed(
            'Use one transaction ({"op": "TransactWriteItems", ...}), so the payment and the total change together or not at all.'
        )
    run.run(run.answer)  # the same payment, delivered again
    paid = records(
        run.last(_j({"op": "GetItem", "TableName": T, "Key": LOAN_KEY, "ProjectionExpression": "paid_cents"}))
    )
    payment = records(
        run.last(
            _j(
                {
                    "op": "GetItem",
                    "TableName": T,
                    "Key": {"PK": {"S": "LOAN#L0000006"}, "SK": {"S": PAYMENT_SK}},
                }
            )
        )
    )
    total = paid[0].get("paid_cents") if paid else None
    expected = {"payment item": "exists", "paid_cents after two deliveries": 65781}
    got = {"payment item": "exists" if payment else "missing", "paid_cents after two deliveries": total}
    if not payment:
        return failed("The payment item was not written.", expected, got)
    if total is None or int(total) != 65781:
        return failed(
            "After the same payment arrived twice, paid_cents is not 65781: the total was added twice (or not at all). "
            "Make the Put conditional (attribute_not_exists(SK)) so a replay cancels the whole transaction.",
            expected,
            got,
        )
    return passed("The replay was cancelled as a whole: paid_cents counts the payment once.", expected, got)


LESSON = Lesson(
    id="ch05",
    number=5,
    title="Amazon DynamoDB, with DynamoDB Local",
    database="DynamoDB Local 3.3",
    summary="Access patterns, single-table design, GSI versus scan cost, conditional writes, transactions and TTL.",
    guide=GuideRef(5, "5. Amazon DynamoDB, with DynamoDB Local"),
    consoles=("dynamodb",),
    services=("dynamodb",),
    make_up="make up-05",
    prepare=prepare_dynamodb,
    prepare_note="Recreates the table larkspur_studio with the lab's 18,814 items (about 5 seconds) and a small larkspur_studio_sessions table.",
    steps=(
        Step(
            id="access-patterns",
            title="Start from the access patterns",
            guide=GuideRef(5, "Start from the access patterns"),
            prose=(
                "Write down every access pattern, then design keys so that each is one `GetItem` or `Query`. The table `larkspur_studio` uses generic keys `PK` and `SK` with prefixed values (`BORROWER#B001532`, `APP#A0000006`): **single-table design**.",
                'The console takes **PartiQL** (`SELECT ... FROM larkspur_studio WHERE PK = \'...\'`) or a **JSON API mode**: one object like `{"op": "Query", ...}` with values in DynamoDB JSON (`{"S": "..."}`), as the AWS CLI takes them. JSON mode always reports ConsumedCapacity; DynamoDB Local does not report it for PartiQL.',
            ),
            examples=(
                Example(
                    "AP1 as GetItem (JSON mode)",
                    "dynamodb",
                    _j(
                        {
                            "op": "GetItem",
                            "TableName": T,
                            "Key": {"PK": {"S": "BORROWER#B001532"}, "SK": {"S": "PROFILE"}},
                        }
                    ),
                ),
                Example("The table and its index", "dynamodb", _j({"op": "DescribeTable", "TableName": T})),
                Example("How many items", "dynamodb", _j({"op": "Scan", "TableName": T, "Select": "COUNT"})),
            ),
            exercises=(
                Exercise(
                    id="ch05.profile",
                    number="5.1",
                    title="AP1: a borrower's profile",
                    console="dynamodb",
                    task="Read borrower B001532's profile item: partition key `BORROWER#B001532`, sort key `PROFILE`. PartiQL or JSON mode.",
                    starter=f"SELECT * FROM {T} WHERE PK = 'BORROWER#B001532'",
                    hints=(
                        "The starter returns the whole item collection; name the sort key too.",
                        "AND SK = 'PROFILE'",
                        "In JSON mode: GetItem with a Key of PK and SK.",
                    ),
                    solution=f"SELECT * FROM {T} WHERE PK = 'BORROWER#B001532' AND SK = 'PROFILE'",
                    check=Match(fields=("PK", "SK", "full_name", "annual_income")),
                    wrong=(f"SELECT * FROM {T} WHERE PK = 'BORROWER#B001533' AND SK = 'PROFILE'",),
                    explain="One item by its full primary key: the cheapest read there is.",
                ),
                Exercise(
                    id="ch05.collection",
                    number="5.2",
                    title="AP2: one request for a borrower's screen",
                    console="dynamodb",
                    task="Return everything stored under borrower B001532 (profile, applications, loan references) with one request: `PK`, `SK` and `type` of each item.",
                    starter=f"SELECT PK, SK, type FROM {T} WHERE PK = 'BORROWER#B001532' AND SK = 'PROFILE'",
                    hints=(
                        "Items that share a partition key form an item collection.",
                        "Name only the partition key.",
                        f"SELECT PK, SK, type FROM {T} WHERE PK = 'BORROWER#B001532'",
                    ),
                    solution=f"SELECT PK, SK, type FROM {T} WHERE PK = 'BORROWER#B001532'",
                    check=Match(fields=("PK", "SK", "type")),
                    wrong=(
                        f"SELECT PK, SK, type FROM {T} WHERE PK = 'BORROWER#B001532' AND SK = 'PROFILE'",
                        f"SELECT PK, SK, type FROM {T} WHERE PK = 'BORROWER#B001532' AND begins_with(SK, 'APP#')",
                    ),
                    explain="A pre-joined item collection: what SQL would need a three-table join for.",
                ),
                Exercise(
                    id="ch05.range",
                    number="5.3",
                    title="AP3: a date range, end date included",
                    console="dynamodb",
                    task=(
                        "Return the payments of loan L0000307 made from 2025-04-01 to 2025-06-30, both days included, oldest first. "
                        "Payment sort keys look like `PAYMENT#2025-06-30T12:04:41+00:00#<event_id>`."
                    ),
                    starter=f"SELECT SK, amount_cents FROM {T}\nWHERE PK = 'LOAN#L0000307' AND SK BETWEEN 'PAYMENT#2025-04-01' AND 'PAYMENT#2025-06-30'",
                    hints=(
                        "Run the starter: how many payments, and is there one on 30 June?",
                        "'PAYMENT#2025-06-30T12:04...' sorts after 'PAYMENT#2025-06-30': strings compare character by character.",
                        "End the range with a character that sorts after any timestamp character, for example 'PAYMENT#2025-06-30~'.",
                    ),
                    solution=f"SELECT SK, amount_cents FROM {T}\nWHERE PK = 'LOAN#L0000307' AND SK BETWEEN 'PAYMENT#2025-04-01' AND 'PAYMENT#2025-06-30~'",
                    check=Match(fields=("SK",), ordered=True),
                    wrong=(
                        f"SELECT SK, amount_cents FROM {T} WHERE PK = 'LOAN#L0000307' AND SK BETWEEN 'PAYMENT#2025-04-01' AND 'PAYMENT#2025-06-30'",
                        f"SELECT SK, amount_cents FROM {T} WHERE PK = 'LOAN#L0000307' AND SK BETWEEN 'PAYMENT#2025-04-02' AND 'PAYMENT#2025-06-30~'",
                    ),
                    explain="ISO timestamps sort correctly as strings, which is why a date range becomes a BETWEEN on the sort key; the end needs care.",
                ),
            ),
        ),
        Step(
            id="gsi",
            title="Global secondary indexes, and what a scan costs",
            guide=GuideRef(5, "Global secondary indexes"),
            prose=(
                "Applications by status is not the table's key, so application items also carry `GSI1PK = STATUS#<status>` and `GSI1SK = <submitted_at>`: a **global secondary index** keyed differently. GSI reads are always eventually consistent.",
                "A `FilterExpression` is applied after items are read: you pay for everything scanned. Compare `Count` with `ScannedCount` in every read you write.",
            ),
            examples=(
                Example(
                    "Count the funded applications through the index",
                    "dynamodb",
                    _j(
                        {
                            "op": "Query",
                            "TableName": T,
                            "IndexName": "GSI1",
                            "KeyConditionExpression": "GSI1PK = :s",
                            "ExpressionAttributeValues": {":s": {"S": "STATUS#funded"}},
                            "Select": "COUNT",
                        }
                    ),
                ),
            ),
            exercises=(
                Exercise(
                    id="ch05.gsi",
                    number="5.4",
                    title="AP4 through the index",
                    console="dynamodb",
                    task="In JSON mode, query `GSI1` for declined applications submitted on or after 2025-06-01, newest first. The check wants every item read to be one returned.",
                    starter=_j(
                        {
                            "op": "Query",
                            "TableName": T,
                            "IndexName": "GSI1",
                            "KeyConditionExpression": "GSI1PK = :s",
                            "ExpressionAttributeValues": {":s": {"S": "STATUS#declined"}},
                        }
                    ),
                    hints=(
                        "Add a sort-key condition: AND GSI1SK >= :from.",
                        'Add ":from": {"S": "2025-06-01"} to ExpressionAttributeValues.',
                        '"ScanIndexForward": false gives newest first.',
                    ),
                    solution=GSI_QUERY,
                    check=Custom(check_gsi),
                    wrong=(
                        SCAN_QUERY,
                        _j(
                            {
                                "op": "Query",
                                "TableName": T,
                                "IndexName": "GSI1",
                                "KeyConditionExpression": "GSI1PK = :s",
                                "FilterExpression": "GSI1SK >= :from",
                                "ExpressionAttributeValues": {
                                    ":s": {"S": "STATUS#declined"},
                                    ":from": {"S": "2025-06-01"},
                                },
                            }
                        ),
                    ),
                    explain="117 items for 2.5 RCU, as in the guide's step 5.3.",
                ),
                Exercise(
                    id="ch05.scan",
                    number="5.5",
                    title="The same question as a Scan",
                    console="dynamodb",
                    task="Now measure the expensive way: a `Scan` of the whole table with a `FilterExpression` for the same items (declined, submitted since 2025-06-01), following every page.",
                    starter=_j(
                        {
                            "op": "Scan",
                            "TableName": T,
                            "FilterExpression": "GSI1PK = :s",
                            "ExpressionAttributeValues": {":s": {"S": "STATUS#declined"}},
                        }
                    ),
                    hints=(
                        "The filter needs both conditions: GSI1PK = :s AND GSI1SK >= :from.",
                        "Leave pagination on: the console follows LastEvaluatedKey like the AWS CLI.",
                        "Compare ScannedCount and ConsumedCapacity with exercise 5.4.",
                    ),
                    solution=SCAN_QUERY,
                    check=Custom(check_scan),
                    wrong=(
                        GSI_QUERY,
                        _j({**json.loads(SCAN_QUERY), "paginate": False}),
                    ),
                    explain="The guide's step 5.4: 3 pages, 18,814 items read, 305 RCU, for the same 117 items.",
                ),
            ),
        ),
        Step(
            id="conditional",
            title="Conditional writes",
            guide=GuideRef(5, "Conditional writes"),
            prose=(
                "Every write can carry a `ConditionExpression`, checked atomically against the current item: `attribute_not_exists(PK)` for insert-if-absent, `version = :expected` for optimistic locking.",
                "`status` is a reserved word in expressions: write `#s` and map it in `ExpressionAttributeNames`. In PartiQL, `INSERT` is already insert-if-absent: it fails with `DuplicateItem`.",
                "Each check runs your write twice and changes the item in between, as a competing writer would.",
            ),
            exercises=(
                Exercise(
                    id="ch05.claim",
                    number="5.6",
                    title="Insert if absent",
                    console="dynamodb",
                    task="Claim payment id demo-7: write the item `PK` = `PAYMENT_ID#demo-7`, `SK` = `CLAIM`, `claimed_by` = `worker-1`, but only if no such item exists.",
                    starter=_j(
                        {
                            "op": "PutItem",
                            "TableName": T,
                            "Item": {
                                "PK": {"S": "PAYMENT_ID#demo-7"},
                                "SK": {"S": "CLAIM"},
                                "claimed_by": {"S": "worker-1"},
                            },
                        }
                    ),
                    hints=(
                        "A plain PutItem overwrites an existing item silently.",
                        'Add "ConditionExpression": "attribute_not_exists(PK)".',
                        "Or in PartiQL: INSERT INTO larkspur_studio VALUE {'PK': ..., 'SK': ..., 'claimed_by': ...}",
                    ),
                    solution=_j(
                        {
                            "op": "PutItem",
                            "TableName": T,
                            "Item": {
                                "PK": {"S": "PAYMENT_ID#demo-7"},
                                "SK": {"S": "CLAIM"},
                                "claimed_by": {"S": "worker-1"},
                            },
                            "ConditionExpression": "attribute_not_exists(PK)",
                        }
                    ),
                    check=Verify(
                        setup=f"DELETE FROM {T} WHERE PK = 'PAYMENT_ID#demo-7' AND SK = 'CLAIM'",
                        runs=2,
                        between=_j(
                            {
                                "op": "UpdateItem",
                                "TableName": T,
                                "Key": {"PK": {"S": "PAYMENT_ID#demo-7"}, "SK": {"S": "CLAIM"}},
                                "UpdateExpression": "SET claimed_by = :w",
                                "ConditionExpression": "attribute_exists(PK)",
                                "ExpressionAttributeValues": {":w": {"S": "worker-2"}},
                            }
                        ),
                        between_may_fail=True,
                        allow_errors=True,
                        verify=f"SELECT PK, SK, claimed_by FROM {T} WHERE PK = 'PAYMENT_ID#demo-7' AND SK = 'CLAIM'",
                        verify_each_run=True,
                    ),
                    wrong=(
                        _j(
                            {
                                "op": "PutItem",
                                "TableName": T,
                                "Item": {
                                    "PK": {"S": "PAYMENT_ID#demo-7"},
                                    "SK": {"S": "CLAIM"},
                                    "claimed_by": {"S": "worker-1"},
                                },
                            }
                        ),
                        _j(
                            {
                                "op": "PutItem",
                                "TableName": T,
                                "Item": {
                                    "PK": {"S": "PAYMENT_ID#demo-7"},
                                    "SK": {"S": "CLAIM"},
                                    "claimed_by": {"S": "worker-1"},
                                },
                                "ConditionExpression": "attribute_exists(PK)",
                            }
                        ),
                    ),
                    explain="The DynamoDB version of Redis SET NX and Cassandra IF NOT EXISTS.",
                ),
                Exercise(
                    id="ch05.lock",
                    number="5.7",
                    title="Optimistic locking",
                    console="dynamodb",
                    task="On loan L0000006's `DETAILS` item, set `status` to `closed` and add 1 to `version`, but only if `version` is still 1.",
                    starter=_j(
                        {
                            "op": "UpdateItem",
                            "TableName": T,
                            "Key": LOAN_KEY,
                            "UpdateExpression": "SET #s = :s, version = version + :one",
                            "ExpressionAttributeNames": {"#s": "status"},
                            "ExpressionAttributeValues": {":s": {"S": "closed"}, ":one": {"N": "1"}},
                        }
                    ),
                    hints=(
                        "Add a ConditionExpression on version.",
                        '"ConditionExpression": "version = :v" with ":v": {"N": "1"}.',
                        "A stale writer then gets ConditionalCheckFailedException and changes nothing.",
                    ),
                    solution=_j(
                        {
                            "op": "UpdateItem",
                            "TableName": T,
                            "Key": LOAN_KEY,
                            "UpdateExpression": "SET #s = :s, version = version + :one",
                            "ConditionExpression": "version = :v",
                            "ExpressionAttributeNames": {"#s": "status"},
                            "ExpressionAttributeValues": {
                                ":s": {"S": "closed"},
                                ":one": {"N": "1"},
                                ":v": {"N": "1"},
                            },
                        }
                    ),
                    check=Verify(
                        setup=_j(
                            {
                                "op": "UpdateItem",
                                "TableName": T,
                                "Key": LOAN_KEY,
                                "UpdateExpression": "SET #s = :s, version = :one",
                                "ExpressionAttributeNames": {"#s": "status"},
                                "ExpressionAttributeValues": {":s": {"S": "active"}, ":one": {"N": "1"}},
                            }
                        ),
                        runs=2,
                        between=_j(
                            {
                                "op": "UpdateItem",
                                "TableName": T,
                                "Key": LOAN_KEY,
                                "UpdateExpression": "SET #s = :s, version = :three",
                                "ExpressionAttributeNames": {"#s": "status"},
                                "ExpressionAttributeValues": {":s": {"S": "active"}, ":three": {"N": "3"}},
                            }
                        ),
                        allow_errors=True,
                        verify=_j(
                            {
                                "op": "GetItem",
                                "TableName": T,
                                "Key": LOAN_KEY,
                                "ProjectionExpression": "PK, SK, #s, version",
                                "ExpressionAttributeNames": {"#s": "status"},
                            }
                        ),
                        verify_each_run=True,
                    ),
                    wrong=(
                        _j(
                            {
                                "op": "UpdateItem",
                                "TableName": T,
                                "Key": LOAN_KEY,
                                "UpdateExpression": "SET #s = :s, version = version + :one",
                                "ExpressionAttributeNames": {"#s": "status"},
                                "ExpressionAttributeValues": {":s": {"S": "closed"}, ":one": {"N": "1"}},
                            }
                        ),
                        _j(
                            {
                                "op": "UpdateItem",
                                "TableName": T,
                                "Key": LOAN_KEY,
                                "UpdateExpression": "SET #s = :s, version = :two",
                                "ConditionExpression": "version = :v",
                                "ExpressionAttributeNames": {"#s": "status"},
                                "ExpressionAttributeValues": {
                                    ":s": {"S": "closed"},
                                    ":two": {"N": "2"},
                                    ":v": {"N": "3"},
                                },
                            }
                        ),
                    ),
                    explain="The guide's step 5.5: writer A applied, stale writer B got ConditionalCheckFailedException.",
                ),
            ),
        ),
        Step(
            id="transactions",
            title="Transactions",
            guide=GuideRef(5, "Transactions"),
            prose=(
                '`TransactWriteItems` applies up to 100 actions across items and tables, all or nothing. A conditional insert plus a non-idempotent update in one transaction makes "add to the total" safe against retries.',
                "When a transaction is cancelled, `CancellationReasons` lists one entry per action, in order.",
            ),
            exercises=(
                Exercise(
                    id="ch05.transaction",
                    number="5.8",
                    title="Record a payment and its total, once",
                    console="dynamodb",
                    task=(
                        f"In one transaction, put the payment item `PK` = `LOAN#L0000006`, `SK` = `{PAYMENT_SK}`, `amount_cents` = 65781, "
                        "and add 65781 to `paid_cents` on the loan's `DETAILS` item. The check delivers the same payment twice: the total must count it once."
                    ),
                    starter=_j(
                        {
                            "op": "TransactWriteItems",
                            "TransactItems": [
                                {
                                    "Put": {
                                        "TableName": T,
                                        "Item": {
                                            "PK": {"S": "LOAN#L0000006"},
                                            "SK": {"S": PAYMENT_SK},
                                            "amount_cents": {"N": "65781"},
                                        },
                                    }
                                },
                                {
                                    "Update": {
                                        "TableName": T,
                                        "Key": LOAN_KEY,
                                        "UpdateExpression": "ADD paid_cents :a",
                                        "ExpressionAttributeValues": {":a": {"N": "65781"}},
                                    }
                                },
                            ],
                        }
                    ),
                    hints=(
                        "Run the starter twice: what is paid_cents?",
                        "One action needs a ConditionExpression; if it fails, the whole transaction is cancelled.",
                        'On the Put: "ConditionExpression": "attribute_not_exists(SK)".',
                    ),
                    solution=_j(
                        {
                            "op": "TransactWriteItems",
                            "TransactItems": [
                                {
                                    "Put": {
                                        "TableName": T,
                                        "Item": {
                                            "PK": {"S": "LOAN#L0000006"},
                                            "SK": {"S": PAYMENT_SK},
                                            "amount_cents": {"N": "65781"},
                                        },
                                        "ConditionExpression": "attribute_not_exists(SK)",
                                    }
                                },
                                {
                                    "Update": {
                                        "TableName": T,
                                        "Key": LOAN_KEY,
                                        "UpdateExpression": "ADD paid_cents :a",
                                        "ExpressionAttributeValues": {":a": {"N": "65781"}},
                                    }
                                },
                            ],
                        }
                    ),
                    check=Custom(
                        check_transaction,
                        setup=_j(
                            [
                                {
                                    "op": "DeleteItem",
                                    "TableName": T,
                                    "Key": {"PK": {"S": "LOAN#L0000006"}, "SK": {"S": PAYMENT_SK}},
                                },
                                {
                                    "op": "UpdateItem",
                                    "TableName": T,
                                    "Key": LOAN_KEY,
                                    "UpdateExpression": "REMOVE paid_cents",
                                },
                            ]
                        ),
                    ),
                    wrong=(
                        _j(
                            {
                                "op": "TransactWriteItems",
                                "TransactItems": [
                                    {
                                        "Put": {
                                            "TableName": T,
                                            "Item": {
                                                "PK": {"S": "LOAN#L0000006"},
                                                "SK": {"S": PAYMENT_SK},
                                                "amount_cents": {"N": "65781"},
                                            },
                                        }
                                    },
                                    {
                                        "Update": {
                                            "TableName": T,
                                            "Key": LOAN_KEY,
                                            "UpdateExpression": "ADD paid_cents :a",
                                            "ExpressionAttributeValues": {":a": {"N": "65781"}},
                                        }
                                    },
                                ],
                            }
                        ),
                        _j(
                            [
                                {
                                    "op": "UpdateItem",
                                    "TableName": T,
                                    "Key": LOAN_KEY,
                                    "UpdateExpression": "ADD paid_cents :a",
                                    "ExpressionAttributeValues": {":a": {"N": "65781"}},
                                },
                                {
                                    "op": "PutItem",
                                    "TableName": T,
                                    "Item": {
                                        "PK": {"S": "LOAN#L0000006"},
                                        "SK": {"S": PAYMENT_SK},
                                        "amount_cents": {"N": "65781"},
                                    },
                                    "ConditionExpression": "attribute_not_exists(SK)",
                                },
                            ]
                        ),
                    ),
                    explain="The replay failed with TransactionCanceledException, reasons ['ConditionalCheckFailed', 'None']: the update was cancelled with it.",
                ),
            ),
        ),
        Step(
            id="ttl",
            title="Time to live",
            guide=GuideRef(5, "Time to live"),
            prose=(
                "TTL deletes items whose chosen attribute (a Unix timestamp in seconds) is in the past, in the background: the service documents that it typically happens within a few days, and until then reads still return the item.",
                "So if correctness depends on expiry, filter on it in every read. `larkspur_studio_sessions` holds three tokens for `SESSION#demo`; one expired on 1 January 2025.",
            ),
            examples=(
                Example(
                    "TTL settings of the table", "dynamodb", _j({"op": "DescribeTimeToLive", "TableName": T})
                ),
                Example(
                    "Every token, expired or not",
                    "dynamodb",
                    "SELECT * FROM larkspur_studio_sessions WHERE PK = 'SESSION#demo'",
                ),
            ),
            exercises=(
                Exercise(
                    id="ch05.ttl",
                    number="5.9",
                    title="Read only what has not expired",
                    console="dynamodb",
                    task=(
                        "Return the tokens of `SESSION#demo` in `larkspur_studio_sessions` that have not expired at 1 January 2026 00:00 UTC "
                        "(epoch seconds 1767225600): `expires_at` must be later than that."
                    ),
                    starter="SELECT * FROM larkspur_studio_sessions WHERE PK = 'SESSION#demo'",
                    hints=(
                        "Add a condition on expires_at.",
                        "In PartiQL: AND expires_at > 1767225600",
                        'In JSON mode: a Query with "FilterExpression": "expires_at > :now".',
                    ),
                    solution="SELECT * FROM larkspur_studio_sessions WHERE PK = 'SESSION#demo' AND expires_at > 1767225600",
                    check=Match(fields=("PK", "SK")),
                    wrong=(
                        "SELECT * FROM larkspur_studio_sessions WHERE PK = 'SESSION#demo' AND expires_at < 1767225600",
                    ),
                    explain="In production you pass the current time; TTL is a background delete, not a read filter.",
                ),
            ),
        ),
    ),
)
