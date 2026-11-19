from __future__ import annotations

import json
from datetime import UTC, datetime

from nosqlde import flatten

DOC = {
    "_id": "A1",
    "application_id": "A1",
    "borrower": {"borrower_id": "B1", "employment": {"status": "employed", "years": 3}},
    "tags": ["x", "y"],
    "documents": [
        {"doc_type": "payslip", "verified": True},
        {"doc_type": "id_proof", "verified": False},
    ],
    "decision": {"score": 700, "reasons": ["policy_rule", "affordability"]},
    "product": "auto",
    "loan": {"loan_id": "L1", "principal": 5000.0},
}


def test_nested_objects_become_prefixed_columns() -> None:
    flat = flatten.flatten_document(DOC)
    assert flat["borrower__borrower_id"] == "B1"
    assert flat["borrower__employment__years"] == 3
    assert "borrower" not in flat


def test_arrays_are_kept_as_json_text() -> None:
    flat = flatten.flatten_document({"t": [1, {"a": datetime(2025, 1, 1, tzinfo=UTC)}]})
    assert json.loads(flat["t"]) == [1, {"a": "2025-01-01T00:00:00+00:00"}]


def test_skip_only_applies_at_top_level() -> None:
    flat = flatten.flatten_document(DOC, skip=frozenset({"_id", "loan"}))
    assert "_id" not in flat and not any(k.startswith("loan") for k in flat)


def test_explode_carries_parent_key_and_position() -> None:
    rows = flatten.explode(DOC, "documents", "application_id")
    assert rows == [
        {"application_id": "A1", "position": 0, "doc_type": "payslip", "verified": True},
        {"application_id": "A1", "position": 1, "doc_type": "id_proof", "verified": False},
    ]


def test_explode_scalars_and_missing_arrays() -> None:
    assert flatten.explode(DOC, "tags", "application_id")[1] == {
        "application_id": "A1",
        "position": 1,
        "value": "y",
    }
    assert flatten.explode({"application_id": "A2"}, "documents", "application_id") == []
    assert flatten.explode({"application_id": "A2", "documents": None}, "documents", "application_id") == []


def test_flatten_application_splits_into_four_tables() -> None:
    tables = flatten.flatten_application(DOC)
    assert len(tables["applications"]) == 1
    assert "decision__reasons" not in tables["applications"][0]
    assert [r["reason"] for r in tables["decline_reasons"]] == ["policy_rule", "affordability"]
    assert len(tables["application_documents"]) == 2
    assert tables["loans"] == [
        {"loan_id": "L1", "principal": 5000.0, "application_id": "A1", "borrower_id": "B1", "product": "auto"}
    ]


def test_application_without_loan_or_decision() -> None:
    tables = flatten.flatten_application(
        {"application_id": "A3", "borrower": {"borrower_id": "B3"}, "product": "auto"}
    )
    assert tables["loans"] == [] and tables["decline_reasons"] == [] and tables["application_documents"] == []
