from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

from nosqlde import recon


def test_canonical_makes_equal_values_equal() -> None:
    assert recon.canonical(12500.0) == recon.canonical(Decimal("12500.00")) == "12500"
    assert recon.canonical(0.1113) == recon.canonical(Decimal("0.1113"))
    naive = datetime(2025, 1, 1, 12, 0)
    aware = datetime(2025, 1, 1, 14, 0, tzinfo=timezone(timedelta(hours=2)))
    assert recon.canonical(naive) == recon.canonical(aware) == "2025-01-01T12:00:00.000000Z"
    assert recon.canonical(None) != recon.canonical("")
    assert recon.canonical(True) == "true"


def test_fingerprint_is_order_independent() -> None:
    rows = [("a", 1), ("b", 2), ("c", 3)]
    assert recon.fingerprint(rows) == recon.fingerprint(list(reversed(rows)))


def test_fingerprint_detects_duplicates_changes_and_losses() -> None:
    rows = [("a", 1), ("b", 2), ("c", 3)]
    base = recon.fingerprint(rows)
    assert recon.fingerprint([*rows, ("a", 1)]) != base
    assert recon.fingerprint([("a", 1), ("b", 2), ("c", 4)]).count == base.count
    assert recon.fingerprint([("a", 1), ("b", 2), ("c", 4)]) != base
    assert recon.fingerprint(rows[:2]) != base


def test_reconcile_result_lines() -> None:
    ok = recon.reconcile("t", [("a", datetime(2025, 1, 1, tzinfo=UTC))], [("a", datetime(2025, 1, 1))])
    assert ok.ok and ok.line().startswith("OK")
    bad = recon.reconcile("t", [("a",), ("b",)], [("a",)])
    assert not bad.ok and "FAIL" in bad.line() and "-1 rows" in bad.line()
    assert "rows, checksum" in str(bad.source)
