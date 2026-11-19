"""The DynamoDB console: PartiQL (ExecuteStatement), plus a JSON API mode.

* Text that starts with `{` or `[` is JSON API mode: one object (or an array of them) like
  `{"op": "Query", "TableName": "larkspur_studio", "KeyConditionExpression": ...}`, with
  values in DynamoDB JSON (`{"S": "..."}`, `{"N": "1"}`), as the AWS CLI takes them.
  Every call asks for ReturnConsumedCapacity=TOTAL. Query and Scan follow
  LastEvaluatedKey across pages (up to 50, like the AWS CLI's automatic pagination) and
  add up Count, ScannedCount and ConsumedCapacity; `"paginate": false` reads one page.
* Anything else is PartiQL, one statement per `;`. ExecuteStatement on DynamoDB Local
  3.3.2 does not return ConsumedCapacity (the service does); the console says so, and the
  JSON mode is the way to see a request's cost.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from nosqlde.config import SETTINGS
from nosqlde.studio.runners.base import Block, RunResult, ServiceDown, StudioError, error_block
from nosqlde.studio.runners.cql import split_statements

STUDIO_TABLE = "larkspur_studio"
MAX_PAGES = 50
#: op name -> boto3 method; data-plane calls plus describing tables and TTL
OPERATIONS = {
    "GetItem": "get_item",
    "PutItem": "put_item",
    "UpdateItem": "update_item",
    "DeleteItem": "delete_item",
    "Query": "query",
    "Scan": "scan",
    "BatchGetItem": "batch_get_item",
    "BatchWriteItem": "batch_write_item",
    "TransactGetItems": "transact_get_items",
    "TransactWriteItems": "transact_write_items",
    "ExecuteStatement": "execute_statement",
    "ExecuteTransaction": "execute_transaction",
    "DescribeTable": "describe_table",
    "ListTables": "list_tables",
    "DescribeTimeToLive": "describe_time_to_live",
    "UpdateTimeToLive": "update_time_to_live",
}
CAPACITY_OPS = {
    "GetItem",
    "PutItem",
    "UpdateItem",
    "DeleteItem",
    "Query",
    "Scan",
    "BatchGetItem",
    "BatchWriteItem",
    "TransactGetItems",
    "TransactWriteItems",
    "ExecuteStatement",
    "ExecuteTransaction",
}
PAGED_OPS = {"Query", "Scan"}


def plain_item(item: dict[str, Any]) -> dict[str, Any]:
    """DynamoDB JSON ({"S": ...}) to plain values."""
    from boto3.dynamodb.types import TypeDeserializer

    des = TypeDeserializer()
    return {k: des.deserialize(v) for k, v in item.items()}


def _capacity(resp: dict[str, Any]) -> float | None:
    cc = resp.get("ConsumedCapacity")
    if cc is None:
        return None
    entries = cc if isinstance(cc, list) else [cc]
    return float(sum(float(e.get("CapacityUnits", 0) or 0) for e in entries))


def items_block(command: str, items: list[dict[str, Any]], raw: Any) -> Block:
    plain = [plain_item(i) for i in items]
    columns: list[str] = [c for c in ("PK", "SK") if any(c in p for p in plain)]
    for p in plain:
        for k in p:
            if k not in columns:
                columns.append(k)
    return Block(
        command=command,
        kind="table",
        columns=columns,
        rows=[[p.get(c) for c in columns] for p in plain],
        value=raw,
        data={"items": plain},
    )


def parse_json_requests(text: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as err:
        raise StudioError(
            f"line {err.lineno}, column {err.colno}: {err.msg}. JSON mode takes one object such as "
            '{"op": "GetItem", "TableName": "larkspur_studio", "Key": {"PK": {"S": "..."}, "SK": {"S": "..."}}} '
            "or an array of them (double quotes, no trailing commas).",
            title="Cannot read the JSON",
        ) from None
    requests = payload if isinstance(payload, list) else [payload]
    for req in requests:
        if not isinstance(req, dict) or "op" not in req:
            raise StudioError(
                'every request needs an "op", for example {"op": "Query", ...}', title="Missing op"
            )
        if req["op"] not in OPERATIONS:
            raise StudioError(
                f"op {req['op']!r} is not available in the studio; use one of {', '.join(OPERATIONS)}",
                title="Unknown op",
            )
    return requests


class DynamoRunner:
    console = "dynamodb"

    def __init__(self) -> None:
        self._client: Any = None
        self._lock = threading.Lock()

    def client(self) -> Any:
        with self._lock:
            if self._client is None:
                import boto3
                from botocore.config import Config

                self._client = boto3.client(
                    "dynamodb",
                    endpoint_url=SETTINGS.dynamodb_endpoint,
                    region_name="us-east-1",
                    aws_access_key_id="local",  # DynamoDB Local accepts any key; not secrets
                    aws_secret_access_key="local",
                    config=Config(connect_timeout=2, read_timeout=20, retries={"max_attempts": 1}),
                )
            return self._client

    def close(self) -> None:
        with self._lock:
            self._client = None

    def run(self, text: str, max_rows: int = 200) -> RunResult:
        result = RunResult(self.console)
        start = time.perf_counter()
        stripped = text.strip()
        if not stripped:
            result.blocks.append(Block(command="", kind="text", text="(nothing to run)"))
            return result
        try:
            if stripped[0] in "{[":
                for req in parse_json_requests(stripped):
                    block = self._guard(json.dumps(req), lambda r=req: self._json(r, max_rows))
                    result.blocks.append(block)
                    if block.is_error:
                        break
            else:
                for stmt in split_statements(stripped, line_comments=("--",)):
                    block = self._guard(stmt, lambda s=stmt: self._partiql(s, max_rows))
                    result.blocks.append(block)
                    if block.is_error:
                        break
        except StudioError as err:
            result.blocks.append(error_block(stripped.splitlines()[0][:120], err))
        result.elapsed_ms = (time.perf_counter() - start) * 1000
        return result

    def _guard(self, command: str, fn: Any) -> Block:
        from botocore.exceptions import ClientError, EndpointConnectionError, ParamValidationError

        t0 = time.perf_counter()
        try:
            block: Block = fn()
        except EndpointConnectionError as err:
            block = error_block(
                command,
                ServiceDown(
                    f"DynamoDB Local is not reachable at {SETTINGS.dynamodb_endpoint} ({type(err).__name__}).",
                    title="DynamoDB Local is down",
                    hint="Start it with `make up-05`.",
                ),
            )
        except ClientError as err:
            error = err.response.get("Error", {})
            code = error.get("Code", "ClientError")
            message = error.get("Message", str(err))
            reasons = [r.get("Code", "None") for r in err.response.get("CancellationReasons", [])]
            text = f"{code}: {message}"
            if reasons:
                text += f"\nCancellationReasons (one per action, in order): {reasons}"
            block = error_block(command, StudioError(text, title=code))
            block.data = {"error": code, "message": message, "reasons": reasons}
        except ParamValidationError as err:
            block = error_block(command, StudioError(str(err), title="Invalid request"))
        except StudioError as err:
            block = error_block(command, err)
        except Exception as err:
            if "Could not connect" in str(err) or isinstance(err, OSError):
                block = error_block(
                    command,
                    ServiceDown(
                        f"DynamoDB Local is not reachable at {SETTINGS.dynamodb_endpoint}.",
                        title="DynamoDB Local is down",
                        hint="Start it with `make up-05`.",
                    ),
                )
            else:
                block = error_block(command, err)
        block.elapsed_ms = (time.perf_counter() - t0) * 1000
        return block

    def _partiql(self, stmt: str, max_rows: int) -> Block:
        client = self.client()
        items: list[dict[str, Any]] = []
        pages = 0
        kwargs: dict[str, Any] = {"Statement": stmt, "ReturnConsumedCapacity": "TOTAL"}
        capacity: float | None = None
        last: dict[str, Any] = {}
        while True:
            resp = client.execute_statement(**kwargs)
            pages += 1
            last = resp
            items.extend(resp.get("Items", []))
            cap = _capacity(resp)
            if cap is not None:
                capacity = (capacity or 0.0) + cap
            token = resp.get("NextToken")
            if not token or len(items) >= max_rows or pages >= MAX_PAGES:
                break
            kwargs["NextToken"] = token
        is_select = stmt.lstrip().upper().startswith("SELECT")
        if is_select:
            block = items_block(stmt, items[:max_rows], None)
            block.truncated = len(items) > max_rows or bool(last.get("NextToken"))
            block.notes.append(f"Items: {len(items)}{'+' if block.truncated else ''}, pages: {pages}")
        else:
            block = Block(command=stmt, kind="text", text="OK", data={"items": []})
        if capacity is None:
            block.notes.append(
                "ConsumedCapacity: not reported by DynamoDB Local for ExecuteStatement; "
                'use the JSON mode ({"op": "Query", ...}) to see what a request costs'
            )
        else:
            block.notes.append(f"ConsumedCapacity: {capacity:g} capacity units")
        assert isinstance(block.data, dict)
        block.data["capacity"] = capacity
        return block

    def _json(self, req: dict[str, Any], max_rows: int) -> Block:
        client = self.client()
        op = str(req["op"])
        params = {k: v for k, v in req.items() if k not in ("op", "paginate")}
        paginate = bool(req.get("paginate", True)) and op in PAGED_OPS and "Limit" not in params
        if op in CAPACITY_OPS:
            params.setdefault("ReturnConsumedCapacity", "TOTAL")
        method = getattr(client, OPERATIONS[op])
        command = json.dumps(req)
        if op not in PAGED_OPS:
            resp = method(**params)
            resp.pop("ResponseMetadata", None)
            capacity = _capacity(resp)
            items: list[dict[str, Any]] = []
            if "Item" in resp:
                items = [resp["Item"]]
            elif "Items" in resp:
                items = list(resp["Items"])
            elif op == "TransactGetItems":
                items = [r["Item"] for r in resp.get("Responses", []) if "Item" in r]
            elif op == "BatchGetItem":
                items = [i for rows in resp.get("Responses", {}).values() for i in rows]
            if items or op in ("GetItem", "BatchGetItem", "TransactGetItems") or "Items" in resp:
                block = items_block(command, items, resp)
                block.notes.append(f"Items: {len(items)}")
            else:
                attrs = resp.get("Attributes")
                block = Block(command=command, kind="json", value=resp, data={"items": []})
                if attrs:
                    assert isinstance(block.data, dict)
                    block.data["attributes"] = plain_item(attrs)
            assert isinstance(block.data, dict)
            block.data["capacity"] = capacity
            block.data["response"] = resp
            if capacity is not None:
                block.notes.append(f"ConsumedCapacity: {capacity:g} capacity units")
            return block
        # Query and Scan: follow the pages, like the AWS CLI does
        pages = 0
        all_items: list[dict[str, Any]] = []
        count = scanned = 0
        capacity_total = 0.0
        last: dict[str, Any] = {}
        while True:
            resp = method(**params)
            resp.pop("ResponseMetadata", None)
            pages += 1
            last = resp
            all_items.extend(resp.get("Items", []))
            count += int(resp.get("Count", 0))
            scanned += int(resp.get("ScannedCount", 0))
            capacity_total += _capacity(resp) or 0.0
            key = resp.get("LastEvaluatedKey")
            if not key or not paginate or pages >= MAX_PAGES:
                break
            params["ExclusiveStartKey"] = key
        summary = {
            "Count": count,
            "ScannedCount": scanned,
            "ConsumedCapacity": round(capacity_total, 4),
            "pages": pages,
        }
        if last.get("LastEvaluatedKey"):
            summary["LastEvaluatedKey"] = last["LastEvaluatedKey"]
        block = items_block(command, all_items[:max_rows], summary)
        block.truncated = len(all_items) > max_rows
        block.notes.append(
            f"Count {count}, ScannedCount {scanned}, ConsumedCapacity {capacity_total:g} RCU, {pages} page{'s' if pages != 1 else ''}"
            + (" (stopped at LastEvaluatedKey: more items exist)" if last.get("LastEvaluatedKey") else "")
        )
        assert isinstance(block.data, dict)
        block.data.update({"count": count, "scanned": scanned, "capacity": capacity_total, "pages": pages})
        if len(all_items) > max_rows:
            block.data["items"] = [plain_item(i) for i in all_items]
        return block
