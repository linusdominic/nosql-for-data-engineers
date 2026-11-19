"""Check chapter 5's exercises against DynamoDB Local (table `larkspur_check`)."""

from __future__ import annotations

from datetime import date

from nosqlde import checks, clients, datagen
from nosqlde.labs.ch05_dynamodb import create_table

TABLE = "larkspur_check"


def run(solutions: bool = False) -> int:
    checker, answers = checks.start("Chapter 5 (DynamoDB)", "ch05_dynamodb.py", solutions)
    client = clients.dynamodb_client()
    ddb = clients.dynamodb_resource()
    create_table(client, TABLE)
    tbl = ddb.Table(TABLE)
    world = datagen.generate(seed=42)
    with tbl.batch_writer() as batch:
        for p in world.payments:
            batch.put_item(
                Item={
                    "PK": f"LOAN#{p['loan_id']}",
                    "SK": f"PAYMENT#{p['event_time'].isoformat()}#{p['event_id']}",
                    "amount_cents": p["amount_cents"],
                    # padding makes the table bigger than one 1 MB scan page
                    "note": "x" * 100,
                }
            )

    def ex1() -> str:
        loan_id = "L0000006"
        start, end = date(2025, 3, 1), date(2025, 6, 30)
        want = sorted(
            f"PAYMENT#{p['event_time'].isoformat()}#{p['event_id']}"
            for p in world.payments
            if p["loan_id"] == loan_id and start <= p["event_time"].date() <= end
        )
        got = answers.payments_between(tbl, loan_id, start.isoformat(), end.isoformat())
        got_sk = [i["SK"] for i in got]
        assert got_sk == want, f"expected {len(want)} payments {want}, got {got_sk}"
        edge = next(p for p in world.payments if p["event_time"].date() == date(2025, 3, 31))
        got_edge = answers.payments_between(tbl, edge["loan_id"], "2025-03-31", "2025-03-31")
        assert len(got_edge) >= 1, (
            "a payment made during the end date must be included (an SK like "
            "PAYMENT#2025-03-31T14:00... sorts after PAYMENT#2025-03-31)"
        )
        return f"{len(got)} payments for {loan_id} between {start} and {end}, end date inclusive"

    def ex2() -> str:
        item = {"PK": "CLAIM#evt-1", "SK": "CLAIM", "by": "worker-1"}
        assert answers.put_if_absent(tbl, item) is True, "first write should return True"
        assert answers.put_if_absent(tbl, {**item, "by": "worker-2"}) is False, (
            "second write should return False"
        )
        stored = tbl.get_item(Key={"PK": "CLAIM#evt-1", "SK": "CLAIM"})["Item"]
        assert stored["by"] == "worker-1", f"the first writer must win; stored by={stored['by']}"
        return "written once, second attempt rejected, original kept"

    def ex3() -> str:
        key = {"PK": "LOAN#LX", "SK": "DETAILS"}
        tbl.put_item(Item={**key, "status": "active", "version": 1})
        a = answers.set_status_if_version(tbl, key, "closed", 1)
        b = answers.set_status_if_version(tbl, key, "written_off", 1)
        item = tbl.get_item(Key=key)["Item"]
        assert a is True and b is False, f"expected (True, False), got ({a}, {b})"
        assert item["status"] == "closed" and int(item["version"]) == 2, (
            f"expected status=closed version=2, got status={item['status']} version={item['version']}"
        )
        return "first writer applied (version 1 -> 2), stale writer rejected"

    def ex4() -> str:
        total = tbl.scan(Select="COUNT")
        count = total["Count"]
        kwargs = {"Select": "COUNT"}
        while "LastEvaluatedKey" in total:
            total = tbl.scan(ExclusiveStartKey=total["LastEvaluatedKey"], **kwargs)
            count += total["Count"]
        items = answers.export_items(tbl, 4)
        keys = [(i["PK"], i["SK"]) for i in items]
        assert len(set(keys)) == len(keys), f"{len(keys) - len(set(keys))} items were exported twice"
        assert len(keys) == count, (
            f"table has {count} items, export returned {len(keys)}; did you follow LastEvaluatedKey?"
        )
        return f"{count} items, 4 segments, no duplicates, pagination followed"

    checker.run("5.1 payments_between", ex1)
    checker.run("5.2 put_if_absent", ex2)
    checker.run("5.3 set_status_if_version", ex3)
    checker.run("5.4 export_items", ex4)
    client.delete_table(TableName=TABLE)
    return checker.finish()
