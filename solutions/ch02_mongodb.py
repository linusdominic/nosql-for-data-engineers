"""Chapter 2 reference solutions: MongoDB. Check them with `make check-02 SOLUTIONS=1`."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from pymongo import ASCENDING
from pymongo.collection import Collection


def explode_documents(app: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for position, item in enumerate(app.get("documents") or []):
        rows.append(
            {
                "application_id": app["application_id"],
                "position": position,
                "doc_type": item.get("doc_type"),
                "uploaded_at": item.get("uploaded_at"),
                "verified": item.get("verified"),
            }
        )
    return rows


def approval_rate_pipeline() -> list[dict[str, Any]]:
    approved = {"$cond": [{"$in": ["$status", ["approved", "funded"]]}, 1, 0]}
    return [
        {"$match": {"status": {"$ne": "submitted"}}},
        {"$group": {"_id": "$channel", "decided": {"$sum": 1}, "approved": {"$sum": approved}}},
        {
            "$set": {
                "approval_rate": {"$round": [{"$divide": ["$approved", "$decided"]}, 4]},
            }
        },
        {"$sort": {"_id": 1}},
    ]


def extract_since(
    coll: Collection[dict[str, Any]], watermark: datetime | None
) -> tuple[list[dict[str, Any]], datetime | None]:
    query = {} if watermark is None else {"updated_at": {"$gt": watermark}}
    docs = list(coll.find(query).sort([("updated_at", ASCENDING), ("_id", ASCENDING)]))
    new_watermark = docs[-1]["updated_at"] if docs else watermark
    return docs, new_watermark


def read_changes_after(
    coll: Collection[dict[str, Any]], resume_token: dict[str, Any], expected: int
) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    deadline = time.monotonic() + 10
    with coll.watch(resume_after=resume_token) as stream:
        while len(out) < expected and time.monotonic() < deadline:
            change = stream.try_next()
            if change is not None:
                out.append((change["operationType"], change["documentKey"]["_id"]))
    return out
