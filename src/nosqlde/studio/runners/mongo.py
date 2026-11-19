"""The MongoDB console: the mongosh subset from nosqlde.studio.mongosh, run with pymongo."""

from __future__ import annotations

import threading
import time
from typing import Any

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import (
    BulkWriteError,
    ConnectionFailure,
    OperationFailure,
    PyMongoError,
    ServerSelectionTimeoutError,
    WriteError,
)

from nosqlde.config import SETTINGS
from nosqlde.studio import mongosh
from nosqlde.studio.runners.base import Block, RunResult, ServiceDown, StudioError, error_block

STUDIO_DB = "larkspur_studio"
MAX_TIME_MS = 15_000


def _flatten(doc: Any, prefix: str = "") -> dict[str, Any]:
    """Nested documents to dotted columns, for the table view."""
    out: dict[str, Any] = {}
    if isinstance(doc, dict):
        for k, v in doc.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict) and v and not any(str(x).startswith("$") for x in v):
                out.update(_flatten(v, key))
            else:
                out[key] = v
    else:
        out[prefix or "value"] = doc
    return out


def docs_block(command: str, docs: list[Any], limit_hit: bool) -> Block:
    """Documents as a JSON tree, plus a table of dotted columns."""
    flat = [_flatten(d) for d in docs]
    columns: list[str] = []
    for row in flat:
        for k in row:
            if k not in columns:
                columns.append(k)
    block = Block(
        command=command,
        kind="table",
        columns=columns,
        rows=[[row.get(c) for c in columns] for row in flat],
        value=docs,
        truncated=limit_hit,
        data=docs,
    )
    block.notes.append(
        f"{len(docs)} document{'s' if len(docs) != 1 else ''}" + (" (more not shown)" if limit_hit else "")
    )
    return block


class MongoRunner:
    console = "mongo"

    def __init__(self, database: str = STUDIO_DB, uri: str | None = None) -> None:
        self.database = database
        self.uri = uri or SETTINGS.mongo_uri
        self._client: MongoClient[dict[str, Any]] | None = None
        self._lock = threading.Lock()

    def client(self) -> MongoClient[dict[str, Any]]:
        with self._lock:
            if self._client is None:
                self._client = MongoClient(
                    self.uri, serverSelectionTimeoutMS=2500, tz_aware=True, connectTimeoutMS=2500
                )
            return self._client

    def db(self) -> Database[dict[str, Any]]:
        return self.client()[self.database]

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None

    def run(self, text: str, max_rows: int = 200) -> RunResult:
        result = RunResult(self.console)
        start = time.perf_counter()
        try:
            operations = mongosh.plan_all(text)
        except mongosh.SubsetError as err:
            result.blocks.append(
                Block(
                    command=text.strip().splitlines()[0][:120] if text.strip() else "",
                    kind="error",
                    text=err.render(),
                    error_title="Not in the mongosh subset",
                    hint="This console understands a subset of mongosh. See the list under the editor.",
                )
            )
            result.elapsed_ms = (time.perf_counter() - start) * 1000
            return result
        if not operations:
            result.blocks.append(Block(command="", kind="text", text="(nothing to run)"))
        for op in operations:
            op_start = time.perf_counter()
            try:
                block = self._execute(op, max_rows)
            except (ServerSelectionTimeoutError, ConnectionFailure) as err:
                block = error_block(
                    op.text,
                    ServiceDown(
                        f"MongoDB is not reachable at {self.uri} ({type(err).__name__}).",
                        title="MongoDB is down",
                        hint="Start it with `make up-02` (or `make up-capstone`).",
                    ),
                )
            except (WriteError, BulkWriteError, OperationFailure) as err:
                block = _server_error(op.text, err)
            except mongosh.SubsetError as err:
                block = Block(
                    command=op.text, kind="error", text=err.render(), error_title="Not in the mongosh subset"
                )
            except StudioError as err:
                block = error_block(op.text, err)
            except (PyMongoError, TypeError, ValueError) as err:
                block = error_block(op.text, err, title=type(err).__name__)
            if not block.elapsed_ms:
                block.elapsed_ms = (time.perf_counter() - op_start) * 1000
            result.blocks.append(block)
            if block.is_error:
                break
        result.elapsed_ms = (time.perf_counter() - start) * 1000
        return result

    # ------------------------------------------------------------ execution
    def _execute(self, op: mongosh.Operation, max_rows: int) -> Block:
        start = time.perf_counter()
        block = self._dispatch(op, max_rows)
        block.command = op.text
        block.elapsed_ms = (time.perf_counter() - start) * 1000
        return block

    def _dispatch(self, op: mongosh.Operation, max_rows: int) -> Block:
        db = self.db()
        if op.kind == "show" or (op.kind == "db" and op.method == "getCollectionNames"):
            names = sorted(db.list_collection_names())
            if op.kind == "show":
                return Block(
                    command=op.text, kind="text", text="\n".join(names) or "(no collections)", data=names
                )
            return Block(command=op.text, kind="json", value=names, data=names)
        if op.kind == "db" and op.method == "createCollection":
            options = dict(op.args[1]) if len(op.args) > 1 else {}
            db.create_collection(op.args[0], **options)
            created = {"ok": 1}
            return Block(command=op.text, kind="json", value=created, data=created)
        assert op.collection is not None
        coll = db[op.collection]
        m, a = op.method, op.args
        if m == "find":
            return self._find(op, coll, max_rows)
        if m == "findOne":
            doc = coll.find_one(a[0] if a else {}, a[1] if len(a) > 1 else None, max_time_ms=MAX_TIME_MS)
            if doc is None:
                return Block(command=op.text, kind="text", text="null", data=[])
            return Block(command=op.text, kind="json", value=doc, data=[doc])
        if m == "aggregate":
            options = dict(a[1]) if len(a) > 1 else {}
            options.setdefault("maxTimeMS", MAX_TIME_MS)
            docs: list[Any] = []
            hit = False
            for doc in coll.aggregate(a[0], **options):
                if len(docs) >= max_rows:
                    hit = True
                    break
                docs.append(doc)
            return docs_block(op.text, docs, hit)
        if m == "countDocuments":
            options = dict(a[1]) if len(a) > 1 else {}
            n = coll.count_documents(a[0] if a else {}, maxTimeMS=MAX_TIME_MS, **options)
            return Block(command=op.text, kind="text", text=str(n), data=n)
        if m == "estimatedDocumentCount":
            n = coll.estimated_document_count()
            return Block(command=op.text, kind="text", text=str(n), data=n)
        if m == "distinct":
            values = coll.distinct(a[0], a[1] if len(a) > 1 else None, maxTimeMS=MAX_TIME_MS)
            return Block(command=op.text, kind="json", value=values, data=values)
        if m == "insertOne":
            res = coll.insert_one(a[0])
            reply: Any = {"acknowledged": res.acknowledged, "insertedId": res.inserted_id}
        elif m == "insertMany":
            ordered = bool(a[1].get("ordered", True)) if len(a) > 1 else True
            many = coll.insert_many(a[0], ordered=ordered)
            reply = {
                "acknowledged": many.acknowledged,
                "insertedIds": {str(i): v for i, v in enumerate(many.inserted_ids)},
            }
        elif m in ("updateOne", "updateMany", "replaceOne"):
            options = a[2] if len(a) > 2 else {}
            upsert = bool(options.get("upsert", False))
            unknown = set(options) - {"upsert"}
            if unknown:
                raise StudioError(
                    f"{m}() option(s) not supported in the studio: {', '.join(sorted(unknown))}"
                )
            fn: Any = {
                "updateOne": coll.update_one,
                "updateMany": coll.update_many,
                "replaceOne": coll.replace_one,
            }[m]
            upd = fn(a[0], a[1], upsert=upsert)
            reply = {
                "acknowledged": upd.acknowledged,
                "insertedId": upd.upserted_id,
                "matchedCount": upd.matched_count,
                "modifiedCount": upd.modified_count,
                "upsertedCount": 1 if upd.upserted_id is not None else 0,
            }
        elif m in ("deleteOne", "deleteMany"):
            dele = (coll.delete_one if m == "deleteOne" else coll.delete_many)(a[0])
            reply = {"acknowledged": dele.acknowledged, "deletedCount": dele.deleted_count}
        elif m == "createIndex":
            keys = list(a[0].items())
            options = dict(a[1]) if len(a) > 1 else {}
            name = coll.create_index(keys, **options)
            return Block(command=op.text, kind="text", text=name, data=name)
        elif m == "getIndexes":
            indexes = [dict(ix) for ix in coll.list_indexes()]
            return Block(command=op.text, kind="json", value=indexes, data=indexes)
        elif m == "dropIndex":
            before = len(list(coll.list_indexes()))
            target = a[0] if isinstance(a[0], str) else list(a[0].items())
            coll.drop_index(target)
            reply = {"nIndexesWas": before, "ok": 1}
        elif m == "dropIndexes":
            before = len(list(coll.list_indexes()))
            coll.drop_indexes()
            reply = {"nIndexesWas": before, "msg": "non-_id indexes dropped for collection", "ok": 1}
        elif m == "drop":
            existed = op.collection in db.list_collection_names()
            coll.drop()
            return Block(command=op.text, kind="text", text="true" if existed else "false", data=existed)
        else:  # pragma: no cover - plan() only lets supported methods through
            raise StudioError(f"{m}() is not supported")
        return Block(command=op.text, kind="json", value=reply, data=reply)

    def _find(self, op: mongosh.Operation, coll: Any, max_rows: int) -> Block:
        a = op.args
        flt = a[0] if a else {}
        projection = a[1] if len(a) > 1 else None
        sort: dict[str, Any] | None = None
        limit = 0
        skip = 0
        for name, args in op.cursor:
            if name == "sort":
                sort = args[0]
            elif name == "limit":
                limit = int(args[0])
            elif name == "skip":
                skip = int(args[0])
            elif name == "project":
                projection = args[0]
        verbosity = op.explain
        if verbosity:
            cmd: dict[str, Any] = {"find": coll.name, "filter": flt}
            if projection:
                cmd["projection"] = projection
            if sort:
                cmd["sort"] = sort
            if limit:
                cmd["limit"] = limit
            if skip:
                cmd["skip"] = skip
            explain = coll.database.command("explain", cmd, verbosity=verbosity)
            explain.pop("$clusterTime", None)
            explain.pop("operationTime", None)
            summary = mongosh.explain_summary(explain)
            rows = [[k, v] for k, v in summary.items() if v is not None]
            block = Block(
                command=op.text,
                kind="plan",
                columns=["explain", "value"],
                rows=rows,
                value=explain,
                data={"summary": summary, "explain": explain},
            )
            block.notes.append(f"winning plan: {summary['stages']}")
            return block
        cursor = coll.find(flt, projection, max_time_ms=MAX_TIME_MS)
        if sort:
            cursor = cursor.sort(list(sort.items()))
        if skip:
            cursor = cursor.skip(skip)
        if limit:
            cursor = cursor.limit(limit)
        docs: list[Any] = []
        hit = False
        for doc in cursor:
            if len(docs) >= max_rows:
                hit = True
                break
            docs.append(doc)
        cursor.close()
        return docs_block(op.text, docs, hit)


def _server_error(command: str, err: Exception) -> Block:
    code = getattr(err, "code", None)
    details = getattr(err, "details", None) or {}
    if isinstance(err, BulkWriteError):
        write_errors = details.get("writeErrors") or [{}]
        first = write_errors[0]
        code = first.get("code", code)
        message = first.get("errmsg", str(err))
        info = first.get("errInfo")
    else:
        message = details.get("errmsg") or str(err)
        info = details.get("errInfo")
    text = f"MongoServerError[{code}]: {message}" if code is not None else f"MongoServerError: {message}"
    block = Block(command=command, kind="error", text=text, error_title="MongoDB rejected the command")
    if info:
        block.value = info
        block.kind = "error"
        block.notes.append("Additional information is shown below.")
        block.text += "\nAdditional information: " + _compact(info)
    block.data = {"code": code, "message": message, "errInfo": info}
    return block


def _compact(value: Any) -> str:
    import json

    from nosqlde.studio.runners.base import display

    return json.dumps(display(value), separators=(", ", ": "))
