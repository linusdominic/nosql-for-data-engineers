"""Result comparison for studio checks (no database)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from bson import Decimal128, ObjectId

from nosqlde.studio.compare import canonical, compare, flatten, records
from nosqlde.studio.runners.base import Block

ROWS = [
    {"product": "auto", "loans": 483},
    {"product": "home_improvement", "loans": 501},
    {"product": "personal", "loans": 494},
]


def test_numbers_compare_across_types() -> None:
    assert canonical(1) == canonical(1.0) == canonical(Decimal("1.00")) == canonical(Decimal128("1.0"))
    assert canonical(0.6854) == canonical(Decimal("0.6854"))
    assert canonical(0.1 + 0.2) == canonical(0.3)
    assert canonical(True) != canonical(1)
    assert canonical(-0.0) == canonical(0)


def test_instants_compare_at_millisecond_precision_in_utc() -> None:
    aware = datetime(2025, 4, 30, 23, 1, 15, 123456, tzinfo=UTC)
    naive = datetime(2025, 4, 30, 23, 1, 15, 123000)
    assert canonical(aware) == canonical(naive)
    assert canonical(date(2025, 6, 1)) == "2025-06-01"


def test_ids_and_containers() -> None:
    u = uuid.uuid4()
    assert canonical(u) == str(u)
    oid = ObjectId()
    assert canonical(oid) == str(oid)
    assert canonical({"b": 1, "a": [1, 2]}) == canonical({"a": [1.0, 2], "b": 1})
    assert canonical({1, 2}) == canonical({2, 1})


def test_flatten_documents_and_arrays_of_documents() -> None:
    doc = {
        "_id": "A",
        "borrower": [{"full_name": "Dalia"}],
        "x": {"y": {"z": 1}},
        "tags": ["a", "b"],
        "e": {},
    }
    assert flatten(doc) == {
        "_id": "A",
        "borrower.0.full_name": "Dalia",
        "x.y.z": 1,
        "tags": ["a", "b"],
        "e": {},
    }


def test_records_from_every_block_shape() -> None:
    assert records(Block("q", data=[{"a": 1}])) == [{"a": 1}]
    assert records(Block("q", data={"items": [{"PK": "x"}], "capacity": 1.0})) == [{"PK": "x"}]
    assert records(Block("q", data={"records": [{"n": 1}], "plan": {}})) == [{"n": 1}]
    assert records(Block("q", data={"rows": [{"k": 1}], "trace": []})) == [{"k": 1}]
    assert records(Block("q", data=["A0000004", "826"])) == [{"value": "A0000004"}, {"value": "826"}]
    assert records(Block("q", data=42)) == [{"value": 42}]
    assert records(Block("q", data={"response": {"Table": {"Status": "ACTIVE"}}})) == [
        {"response.Table.Status": "ACTIVE"}
    ]


def test_same_rows_in_any_order_pass_unless_order_is_asked_for() -> None:
    assert compare(ROWS, list(reversed(ROWS))).ok
    c = compare(ROWS, list(reversed(ROWS)), ordered=True)
    assert not c.ok and "wrong order" in c.message
    assert compare(ROWS, ROWS, ordered=True).ok


def test_field_subset_and_extra_fields() -> None:
    got = [{**r, "avg_rate": 0.1} for r in ROWS]
    assert compare(ROWS, got).ok
    c = compare(ROWS, got, extra_ok=False)
    assert not c.ok and "avg_rate" in c.message
    assert compare(ROWS, [{"product": r["product"], "loans": 0} for r in ROWS], fields=("product",)).ok


def test_missing_column_names_the_column() -> None:
    c = compare(ROWS, [{"product": r["product"], "n": r["loans"]} for r in ROWS])
    assert not c.ok and "'loans'" in c.message and "n, product" in c.message


def test_by_position_ignores_column_names_but_not_width() -> None:
    assert compare([{"count": 75}], [{"system.count(*)": 75}], by_position=True).ok
    assert not compare([{"count": 75}], [{"c": 76}], by_position=True).ok
    c = compare([{"a": 1, "b": 2}], [{"a": 1}], by_position=True)
    assert not c.ok and "2 columns" in c.message


def test_empty_answer_never_passes_and_empty_reference_is_a_bug() -> None:
    c = compare(ROWS, [])
    assert not c.ok and "nothing" in c.message
    with pytest.raises(ValueError):
        compare([], [])


def test_messages_name_missing_and_unexpected_rows() -> None:
    got = [ROWS[0], ROWS[1], {"product": "personal", "loans": 1}]
    c = compare(ROWS, got)
    assert not c.ok
    assert (
        "1 expected row is missing" in c.message
        and "First missing: product='personal', loans=494" in c.message
    )
    assert "First unexpected" in c.message


def test_duplicates_matter() -> None:
    assert not compare(ROWS, [*ROWS, ROWS[0]]).ok
    assert not compare([*ROWS, ROWS[0]], ROWS).ok
