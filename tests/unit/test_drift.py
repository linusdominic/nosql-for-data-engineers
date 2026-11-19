from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from nosqlde import drift

SCHEMA = {"id": "string", "amount": "decimal", "n": "int", "ok": "bool", "at": "timestamp", "d": "date"}


def test_coerce_safe_conversions() -> None:
    assert drift.coerce("12500.00", "decimal") == Decimal("12500.00")
    assert drift.coerce(12500.0, "decimal") == Decimal("12500.00")
    assert drift.coerce("42", "int") == 42
    assert drift.coerce(42.0, "int") == 42
    assert drift.coerce("true", "bool") is True
    assert drift.coerce(1, "bool") is True
    assert drift.coerce("2025-03-01T10:00:00", "timestamp") == datetime(2025, 3, 1, 10, tzinfo=UTC)
    assert drift.coerce("2025-03-01", "date") == date(2025, 3, 1)
    assert drift.coerce(datetime(2025, 3, 1, 23, tzinfo=UTC), "date") == date(2025, 3, 1)
    assert drift.coerce(7, "string") == "7"


@pytest.mark.parametrize(
    ("value", "target"),
    [
        (42.5, "int"),
        ("abc", "decimal"),
        ("yes", "bool"),
        (2, "bool"),
        ("31/12/2025", "date"),
        ("NaN", "float"),
    ],
)
def test_coerce_refuses_to_guess(value: object, target: str) -> None:
    with pytest.raises(ValueError):
        drift.coerce(value, target)


def test_unknown_target_type() -> None:
    with pytest.raises(ValueError, match="unknown target type"):
        drift.coerce(1, "money")


def test_conform_counts_every_kind_of_drift() -> None:
    rows = [
        {
            "id": "1",
            "amount": 10.0,
            "n": 1,
            "ok": True,
            "at": datetime(2025, 1, 1, tzinfo=UTC),
            "d": date(2025, 1, 1),
        },
        {
            "id": "2",
            "amount": "11.50",
            "n": 2,
            "ok": True,
            "at": datetime(2025, 1, 1, tzinfo=UTC),
            "d": "2025-01-02",
        },
        {"id": "3", "amount": "n/a", "n": 3, "ok": "false", "at": None},
        {
            "id": "4",
            "amount": 1,
            "n": 4,
            "ok": True,
            "at": datetime(2025, 1, 1, tzinfo=UTC),
            "d": date(2025, 1, 1),
            "new": 1,
        },
    ]
    out, report = drift.conform(rows, SCHEMA)
    assert report.rows == 4
    assert report.missing == {"d": 1}
    assert report.coerced == {
        ("amount", "string"): 1,
        ("d", "string"): 1,
        ("ok", "string"): 1,
        ("amount", "int"): 1,
    }
    assert report.failed == {("amount", "string"): 1}
    assert report.unexpected == {"new": 1}
    assert out[2]["amount"] is None and out[2]["ok"] is False and out[2]["d"] is None
    assert out[3][drift.RESCUED] == '{"new": 1}'
    assert out[0][drift.RESCUED] is None
    assert not report.clean
    assert any(line.startswith("failed") for line in report.lines())


def test_float_into_decimal_is_not_drift() -> None:
    _, report = drift.conform([{"id": "1", "amount": 9.99}], {"id": "string", "amount": "decimal"})
    assert report.clean


def test_modes_for_new_fields() -> None:
    rows = [{"id": "1", "extra": True}]
    out, _ = drift.conform(rows, {"id": "string"}, on_new="drop")
    assert out == [{"id": "1"}]
    with pytest.raises(drift.SchemaDriftError):
        drift.conform(rows, {"id": "string"}, on_new="fail")


def test_optional_columns_are_not_reported_missing() -> None:
    out, report = drift.conform(
        [{"id": "1"}], {"id": "string", "loan__id": "string"}, optional=frozenset({"loan__id"})
    )
    assert out[0]["loan__id"] is None and report.missing == {}


def test_infer_schema_shows_mixed_types() -> None:
    seen = drift.infer_schema([{"a": 1}, {"a": "1"}, {"a": None, "b": 2.0}])
    assert seen["a"] == {"int": 1, "string": 1, "null": 1}
    assert seen["b"] == {"float": 1}
