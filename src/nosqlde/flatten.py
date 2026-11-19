"""Turn nested documents into flat tables.

A document database stores one application as one nested object. An analytics engine
wants tables: one row per application, plus one row per uploaded document, plus one row
per decline reason. This module does that split.

The SQL picture: `flatten_document` turns `{"address": {"town": "Fernmouth"}}` into a
column called `address__town`. `explode` turns an array into a child table whose rows
carry the parent's key and their position in the array, exactly like a one-to-many
table with a foreign key.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

SEP = "__"


def flatten_document(
    doc: dict[str, Any], sep: str = SEP, prefix: str = "", skip: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """Flatten nested objects into prefixed columns.

    Arrays are not flattened here (they have no fixed width). They are serialised to a
    JSON string so no data is lost; use `explode` to turn an array into its own table.
    Keys listed in `skip` (top-level only) are left out.
    """
    out: dict[str, Any] = {}
    for key, value in doc.items():
        if not prefix and key in skip:
            continue
        column = f"{prefix}{sep}{key}" if prefix else key
        if isinstance(value, dict):
            out.update(flatten_document(value, sep=sep, prefix=column))
        elif isinstance(value, list):
            out[column] = json.dumps(value, default=_json_default, sort_keys=True)
        else:
            out[column] = value
    return out


def explode(doc: dict[str, Any], array_field: str, parent_key: str, sep: str = SEP) -> list[dict[str, Any]]:
    """One row per element of `doc[array_field]`, carrying the parent key and position.

    Elements that are objects are flattened; scalar elements go into a `value` column.
    A missing or null array produces no rows (not one row of nulls).
    """
    items = doc.get(array_field) or []
    rows: list[dict[str, Any]] = []
    for position, item in enumerate(items):
        row: dict[str, Any] = {parent_key: doc[parent_key], "position": position}
        if isinstance(item, dict):
            row.update(flatten_document(item, sep=sep))
        else:
            row["value"] = item
        rows.append(row)
    return rows


def flatten_application(doc: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Split one application document into rows for four tables.

    Returns {"applications": [1 row], "application_documents": [...],
    "decline_reasons": [...], "loans": [0 or 1 row]}.
    """
    app_id = doc["application_id"]
    parent = flatten_document(doc, skip=frozenset({"_id", "documents", "loan"}))
    parent.pop("decision__reasons", None)  # moved to its own table below
    documents = explode(doc, "documents", "application_id")
    reasons: list[dict[str, Any]] = []
    decision = doc.get("decision") or {}
    for position, reason in enumerate(decision.get("reasons") or []):
        reasons.append({"application_id": app_id, "position": position, "reason": reason})
    loans: list[dict[str, Any]] = []
    if doc.get("loan"):
        loan = flatten_document(doc["loan"])
        loan["application_id"] = app_id
        loan["borrower_id"] = doc["borrower"]["borrower_id"]
        loan["product"] = doc["product"]
        loans.append(loan)
    return {
        "applications": [parent],
        "application_documents": documents,
        "decline_reasons": reasons,
        "loans": loans,
    }


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)
