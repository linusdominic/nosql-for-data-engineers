"""Chapter 5 reference solutions: DynamoDB. Check them with `make check-05 SOLUTIONS=1`."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError


def payments_between(table: Any, loan_id: str, start: str, end: str) -> list[dict[str, Any]]:
    # "~" sorts after every character used in an ISO timestamp, so
    # "PAYMENT#2025-06-30~" is just after every SK on 30 June.
    condition = Key("PK").eq(f"LOAN#{loan_id}") & Key("SK").between(f"PAYMENT#{start}", f"PAYMENT#{end}~")
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {"KeyConditionExpression": condition, "ScanIndexForward": True}
    while True:
        resp = table.query(**kwargs)
        items.extend(resp["Items"])
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def put_if_absent(table: Any, item: dict[str, Any]) -> bool:
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
        return True
    except ClientError as err:
        if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def set_status_if_version(table: Any, key: dict[str, str], new_status: str, expected_version: int) -> bool:
    try:
        table.update_item(
            Key=key,
            UpdateExpression="SET #s = :s, version = version + :one",
            ConditionExpression="version = :v",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": new_status, ":one": 1, ":v": expected_version},
        )
        return True
    except ClientError as err:
        if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def export_items(table: Any, total_segments: int) -> list[dict[str, Any]]:
    def segment(n: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {"Segment": n, "TotalSegments": total_segments}
        while True:
            resp = table.scan(**kwargs)
            items.extend(resp["Items"])
            if "LastEvaluatedKey" not in resp:
                return items
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    with ThreadPoolExecutor(max_workers=total_segments) as pool:
        return [item for part in pool.map(segment, range(total_segments)) for item in part]
