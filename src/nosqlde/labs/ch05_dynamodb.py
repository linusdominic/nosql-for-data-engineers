"""Chapter 5 lab: Amazon DynamoDB, using DynamoDB Local.

Run with `make lab-05` (DynamoDB Local must be up: `make up-05`). The lab deletes and
recreates its tables (`larkspur`, `larkspur_stream`), so it is safe to re-run.
"""

from __future__ import annotations

import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any

import duckdb
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from nosqlde import clients, datagen, lake
from nosqlde.config import SETTINGS
from nosqlde.console import heading, say, step, table

TABLE = "larkspur"


def create_table(client: Any, name: str, stream: bool = False) -> None:
    try:
        client.delete_table(TableName=name)
        client.get_waiter("table_not_exists").wait(TableName=name)
    except ClientError:
        pass
    spec: dict[str, Any] = {
        "TableName": name,
        "BillingMode": "PAY_PER_REQUEST",
        "AttributeDefinitions": [
            {"AttributeName": a, "AttributeType": "S"} for a in ("PK", "SK", "GSI1PK", "GSI1SK")
        ],
        "KeySchema": [
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    }
    if stream:
        spec["StreamSpecification"] = {"StreamEnabled": True, "StreamViewType": "NEW_AND_OLD_IMAGES"}
    client.create_table(**spec)
    client.get_waiter("table_exists").wait(TableName=name)


def items_for(world: datagen.World) -> list[dict[str, Any]]:
    """The single-table layout: every entity type in one table, keyed for its queries."""
    items: list[dict[str, Any]] = []
    for b in world.borrowers:
        items.append(
            {
                "PK": f"BORROWER#{b['borrower_id']}", "SK": "PROFILE", "type": "borrower",
                "full_name": b["full_name"], "town": b["address"]["town"],
                "annual_income": b["annual_income"],
            }
        )  # fmt: skip
    for doc in datagen.applications_as_of(world, world.as_of):
        bid = doc["borrower"]["borrower_id"]
        amount = Decimal(str(doc["requested_amount"]))
        items.append(
            {
                "PK": f"BORROWER#{bid}", "SK": f"APP#{doc['application_id']}", "type": "application",
                "GSI1PK": f"STATUS#{doc['status']}", "GSI1SK": doc["submitted_at"].isoformat(),
                "product": doc["product"], "requested_amount": amount, "channel": doc["channel"],
            }
        )  # fmt: skip
        loan = doc.get("loan")
        if loan:
            lid = loan["loan_id"]
            items.append({"PK": f"BORROWER#{bid}", "SK": f"LOAN#{lid}", "type": "loan_ref"})
            items.append(
                {
                    "PK": f"LOAN#{lid}", "SK": "DETAILS", "type": "loan", "borrower_id": bid,
                    "principal": Decimal(str(loan["principal"])),
                    "annual_rate": Decimal(str(loan["annual_rate"])),
                    "term_months": loan["term_months"], "status": "active", "version": 1,
                    "originated_at": loan["originated_at"].isoformat(),
                }
            )  # fmt: skip
    for p in world.payments:
        items.append(
            {
                "PK": f"LOAN#{p['loan_id']}",
                "SK": f"PAYMENT#{p['event_time'].isoformat()}#{p['event_id']}",
                "type": "payment", "amount_cents": p["amount_cents"], "method": p["method"],
                "instalment_no": p["instalment_no"],
            }
        )  # fmt: skip
    return items


def run() -> None:
    heading("Chapter 5 lab: Amazon DynamoDB (DynamoDB Local)")
    client = clients.dynamodb_client()
    ddb = clients.dynamodb_resource()
    world = datagen.generate(seed=42)
    out = SETTINGS.lake_dir / "ch05"

    # ------------------------------------------------------------------ 5.1
    step("5.1", "Start from the access patterns")
    patterns = [
        ["AP1 borrower profile", "GetItem", "PK=BORROWER#<id>, SK=PROFILE"],
        ["AP2 a borrower's applications and loans", "Query", "PK=BORROWER#<id>"],
        [
            "AP3 a loan's payments in a date range",
            "Query",
            "PK=LOAN#<id>, SK BETWEEN PAYMENT#<from> AND PAYMENT#<to>",
        ],
        [
            "AP4 applications by status, newest first",
            "Query GSI1",
            "GSI1PK=STATUS#<status>, ScanIndexForward=false",
        ],
        ["AP5 loan details", "GetItem", "PK=LOAN#<id>, SK=DETAILS"],
    ]
    table(patterns, ["access pattern", "operation", "key condition"])

    # ------------------------------------------------------------------ 5.2
    step("5.2", "One table for every entity (single-table design)")
    create_table(client, TABLE)
    tbl = ddb.Table(TABLE)
    items = items_for(world)
    start = time.perf_counter()
    with tbl.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)
    say(f"BatchWriteItem: {len(items)} items in {time.perf_counter() - start:.1f}s")
    table(sorted(Counter(i["type"] for i in items).items()), ["item type", "items"])

    # ------------------------------------------------------------------ 5.3
    step("5.3", "Each access pattern is one request")
    loan = next(a for a in datagen.applications_as_of(world, world.as_of) if a["_id"] == "A0000006")
    bid, lid = loan["borrower"]["borrower_id"], loan["loan"]["loan_id"]
    rows = []
    r = tbl.get_item(Key={"PK": f"BORROWER#{bid}", "SK": "PROFILE"}, ReturnConsumedCapacity="TOTAL")
    rows.append(["AP1 GetItem", 1 if "Item" in r else 0, "-", r["ConsumedCapacity"]["CapacityUnits"]])
    r = tbl.query(KeyConditionExpression=Key("PK").eq(f"BORROWER#{bid}"), ReturnConsumedCapacity="TOTAL")
    rows.append(
        [
            "AP2 Query PK=BORROWER#" + bid,
            r["Count"],
            r["ScannedCount"],
            r["ConsumedCapacity"]["CapacityUnits"],
        ]
    )
    r = tbl.query(
        KeyConditionExpression=Key("PK").eq(f"LOAN#{lid}")
        & Key("SK").between("PAYMENT#2025-03", "PAYMENT#2025-07"),
        ReturnConsumedCapacity="TOTAL",
    )
    rows.append(
        [
            f"AP3 Query LOAN#{lid} Mar-Jun",
            r["Count"],
            r["ScannedCount"],
            r["ConsumedCapacity"]["CapacityUnits"],
        ]
    )
    r = tbl.query(
        IndexName="GSI1",
        KeyConditionExpression=Key("GSI1PK").eq("STATUS#declined") & Key("GSI1SK").gte("2025-06-01"),
        ScanIndexForward=False,
        ReturnConsumedCapacity="TOTAL",
    )
    rows.append(
        [
            "AP4 Query GSI1 declined since June",
            r["Count"],
            r["ScannedCount"],
            r["ConsumedCapacity"]["CapacityUnits"],
        ]
    )
    table(rows, ["request", "Count", "ScannedCount", "ConsumedCapacity (RCU)"])

    # ------------------------------------------------------------------ 5.4
    step("5.4", "Scan with a filter reads everything, then throws most of it away")
    scanned = returned = pages = 0
    kwargs: dict[str, Any] = {
        "FilterExpression": Attr("GSI1PK").eq("STATUS#declined") & Attr("GSI1SK").gte("2025-06-01"),
        "ReturnConsumedCapacity": "TOTAL",
    }
    capacity = 0.0
    while True:
        r = tbl.scan(**kwargs)
        pages += 1
        scanned += r["ScannedCount"]
        returned += r["Count"]
        capacity += r["ConsumedCapacity"]["CapacityUnits"]
        if "LastEvaluatedKey" not in r:
            break
        kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    say(
        f"Scan + FilterExpression: {pages} pages (1 MB each at most), ScannedCount={scanned}, "
        f"Count={returned}, ConsumedCapacity={capacity} RCU"
    )
    say(f"the GSI1 query in 5.3 returned the same {rows[3][1]} items and read only those")

    # ------------------------------------------------------------------ 5.5
    step("5.5", "Conditional writes: insert-if-absent and optimistic locking")
    item = {"PK": "PAYMENT_ID#demo-1", "SK": "CLAIM", "type": "claim"}
    outcomes = []
    for attempt in (1, 2):
        try:
            tbl.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
            outcomes.append([f"put #{attempt} attribute_not_exists(PK)", "written"])
        except ClientError as err:
            outcomes.append([f"put #{attempt} attribute_not_exists(PK)", err.response["Error"]["Code"]])
    for writer, new_status in (("writer A", "closed"), ("writer B (stale)", "written_off")):
        try:
            tbl.update_item(
                Key={"PK": f"LOAN#{lid}", "SK": "DETAILS"},
                UpdateExpression="SET #s = :s, version = version + :one",
                ConditionExpression="version = :expected",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": new_status, ":one": 1, ":expected": 1},
            )
            outcomes.append([f"{writer}: SET status={new_status} IF version = 1", "written"])
        except ClientError as err:
            outcomes.append(
                [f"{writer}: SET status={new_status} IF version = 1", err.response["Error"]["Code"]]
            )
    table(outcomes, ["write", "result"])

    # ------------------------------------------------------------------ 5.6
    step("5.6", "Transactions: all or nothing across items")

    def pay(event_key: str) -> str:
        try:
            client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": TABLE,
                            "Item": {
                                "PK": {"S": f"LOAN#{lid}"},
                                "SK": {"S": f"PAYMENT#{event_key}"},
                                "amount_cents": {"N": "65781"},
                            },
                            "ConditionExpression": "attribute_not_exists(SK)",
                        }
                    },
                    {
                        "Update": {
                            "TableName": TABLE,
                            "Key": {"PK": {"S": f"LOAN#{lid}"}, "SK": {"S": "DETAILS"}},
                            "UpdateExpression": "ADD paid_cents :a",
                            "ExpressionAttributeValues": {":a": {"N": "65781"}},
                        }
                    },
                ]
            )
            return "committed"
        except ClientError as err:
            reasons = [r.get("Code", "None") for r in err.response.get("CancellationReasons", [])]
            return f"{err.response['Error']['Code']}, reasons={reasons}"

    first = pay("2026-01-05T09:00:00+00:00#demo")
    again = pay("2026-01-05T09:00:00+00:00#demo")
    paid = tbl.get_item(Key={"PK": f"LOAN#{lid}", "SK": "DETAILS"})["Item"].get("paid_cents")
    say(f"payment + balance update: {first}")
    say(f"same payment again:       {again}")
    say(f"paid_cents on the loan item = {paid} (counted once)")

    # ------------------------------------------------------------------ 5.7
    step("5.7", "DynamoDB Streams: change data capture with a checkpoint")
    streams = clients.dynamodb_streams_client()
    create_table(client, "larkspur_stream", stream=True)
    st = ddb.Table("larkspur_stream")
    arn = client.describe_table(TableName="larkspur_stream")["Table"]["LatestStreamArn"]
    st.put_item(Item={"PK": "LOAN#L1", "SK": "DETAILS", "status": "active"})
    st.update_item(
        Key={"PK": "LOAN#L1", "SK": "DETAILS"},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "delinquent"},
    )
    st.put_item(Item={"PK": "LOAN#L2", "SK": "DETAILS", "status": "active"})

    def read(iterator_args: dict[str, Any]) -> list[dict[str, Any]]:
        shard = streams.describe_stream(StreamArn=arn)["StreamDescription"]["Shards"][0]["ShardId"]
        it = streams.get_shard_iterator(StreamArn=arn, ShardId=shard, **iterator_args)["ShardIterator"]
        records: list[dict[str, Any]] = []
        for _ in range(5):
            resp = streams.get_records(ShardIterator=it)
            records.extend(resp["Records"])
            it = resp.get("NextShardIterator")
            if not it or not resp["Records"]:
                break
        return records

    def describe(rec: dict[str, Any]) -> list[Any]:
        d = rec["dynamodb"]
        old = d.get("OldImage", {}).get("status", {}).get("S")
        new = d.get("NewImage", {}).get("status", {}).get("S")
        return [rec["eventName"], d["Keys"]["PK"]["S"], old, new, d["SequenceNumber"]]

    batch1 = read({"ShardIteratorType": "TRIM_HORIZON"})
    say("first read from TRIM_HORIZON (the oldest record still in the stream):")
    table([describe(r) for r in batch1], ["eventName", "PK", "old status", "new status", "SequenceNumber"])
    checkpoint = batch1[-1]["dynamodb"]["SequenceNumber"]
    say(f"checkpoint saved: SequenceNumber {checkpoint}")
    st.delete_item(Key={"PK": "LOAN#L2", "SK": "DETAILS"})
    st.put_item(Item={"PK": "LOAN#L3", "SK": "DETAILS", "status": "active"})
    batch2 = read({"ShardIteratorType": "AFTER_SEQUENCE_NUMBER", "SequenceNumber": checkpoint})
    say("after 2 more writes, resume with AFTER_SEQUENCE_NUMBER=<checkpoint>:")
    table([describe(r) for r in batch2], ["eventName", "PK", "old status", "new status", "SequenceNumber"])

    # ------------------------------------------------------------------ 5.8
    step("5.8", "Time to live is a background delete, not a read filter")
    client.update_time_to_live(
        TableName=TABLE, TimeToLiveSpecification={"Enabled": True, "AttributeName": "expires_at"}
    )
    expired_at = int(time.time()) - 60
    tbl.put_item(Item={"PK": "SESSION#demo", "SK": "TOKEN", "expires_at": expired_at})
    time.sleep(2)
    still = "Item" in tbl.get_item(Key={"PK": "SESSION#demo", "SK": "TOKEN"})
    say(
        f"TTL enabled on expires_at; item written already expired 60s ago; 2s later GetItem finds it: {still}"
    )
    live = tbl.query(
        KeyConditionExpression=Key("PK").eq("SESSION#demo"),
        FilterExpression=Attr("expires_at").gt(int(time.time())),
    )["Count"]
    say(f"the same read with FilterExpression expires_at > now returns {live} items")

    # ------------------------------------------------------------------ 5.9
    step("5.9", "Export: a parallel scan into Parquet")
    try:
        client.export_table_to_point_in_time(
            TableArn=f"arn:aws:dynamodb:ddblocal:000000000000:table/{TABLE}", S3Bucket="none"
        )
    except ClientError as err:
        say(f"ExportTableToPointInTime on DynamoDB Local -> {err.response['Error']['Code']}")

    def scan_segment(segment: int, total: int) -> list[dict[str, Any]]:
        out_items: list[dict[str, Any]] = []
        kw: dict[str, Any] = {"Segment": segment, "TotalSegments": total}
        while True:
            resp = tbl.scan(**kw)
            out_items.extend(resp["Items"])
            if "LastEvaluatedKey" not in resp:
                return out_items
            kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as pool:
        segments = list(pool.map(lambda s: scan_segment(s, 4), range(4)))
    took = time.perf_counter() - start
    all_items = [i for seg in segments for i in seg]
    distinct = len({(i["PK"], i["SK"]) for i in all_items})
    say(
        f"4 segments returned {[len(s) for s in segments]} items = {len(all_items)} total, "
        f"{distinct} distinct keys, in {took:.2f}s"
    )
    payments = [
        {
            "loan_id": i["PK"].split("#", 1)[1],
            "event_time": i["SK"].split("#")[1],
            "event_id": i["SK"].split("#")[2],
            "amount_cents": int(i["amount_cents"]),
            "method": i.get("method"),
        }
        for i in all_items
        if i.get("type") == "payment"
    ]
    schema = {
        "loan_id": "string",
        "event_time": "string",
        "event_id": "string",
        "amount_cents": "int",
        "method": "string",
    }
    n = lake.write_parquet(payments, out / "payments.parquet", lake.arrow_schema(schema))
    con = duckdb.connect()
    monthly = con.execute(
        f"""SELECT substr(event_time, 1, 7) AS month, count(*) AS payments, sum(amount_cents) / 100 AS amount
            FROM '{out}/payments.parquet' GROUP BY month ORDER BY month LIMIT 4"""
    ).fetchall()
    say(f"wrote {n} payment items to {out}/payments.parquet; first months in DuckDB:")
    table(monthly, ["month", "payments", "amount"])
