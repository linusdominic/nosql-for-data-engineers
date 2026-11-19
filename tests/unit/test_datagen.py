"""The generator is deterministic, fictional, and internally consistent."""

from __future__ import annotations

from datetime import UTC, datetime

from nosqlde import datagen

# The guide quotes these numbers. If the generator changes, update the guide too.
EXPECTED_SUMMARY = {
    "borrowers": 2000,
    "applications": 2393,
    "funded_loans": 1478,
    "payment_events": 11465,
    "late_arriving_events": 340,
    "fraud_rings": 8,
    "ring_applications": 32,
    "households": 60,
    "amount_as_string_docs": 206,
    "missing_employment_docs": 110,
}


def test_default_world_matches_the_numbers_in_the_guide() -> None:
    assert datagen.summary(datagen.generate()) == EXPECTED_SUMMARY


def test_same_seed_same_world() -> None:
    a, b = datagen.generate(seed=7, n_borrowers=200), datagen.generate(seed=7, n_borrowers=200)
    assert a.applications == b.applications
    assert a.payments == b.payments
    assert a.rings == b.rings


def test_different_seed_different_world() -> None:
    a, b = datagen.generate(seed=1, n_borrowers=200), datagen.generate(seed=2, n_borrowers=200)
    assert [x["borrower_id"] for x in a.borrowers] == [x["borrower_id"] for x in b.borrowers]
    assert [x["full_name"] for x in a.borrowers] != [x["full_name"] for x in b.borrowers]


def test_everything_is_visibly_fictional() -> None:
    w = datagen.generate(n_borrowers=300)
    for b in w.borrowers:
        assert b["phone"].startswith("+999 ")
        assert b["email"].endswith("@example.com")
        assert b["address"]["postcode"].startswith("ZZ")
        employer = b["employment"]["employer"]
        assert employer is None or employer.endswith("(fictional)")
    assert datagen.LENDER_NAME.endswith("(fictional)")


def test_application_as_of_moves_through_statuses() -> None:
    w = datagen.generate(n_borrowers=300)
    app = next(a for a in w.applications if a.get("loan"))
    assert datagen.application_as_of(app, app["submitted_at"].replace(year=2024)) is None
    at_submit = datagen.application_as_of(app, app["submitted_at"])
    assert at_submit is not None and at_submit["status"] == "submitted" and "decision" not in at_submit
    decided = datagen.application_as_of(app, app["_decision"]["decided_at"])
    assert decided is not None and decided["status"] == "approved" and "loan" not in decided
    funded = datagen.application_as_of(app, app["loan"]["originated_at"])
    assert funded is not None and funded["status"] == "funded" and funded["loan"]["loan_id"]
    assert funded["updated_at"] == app["loan"]["originated_at"]
    assert not any(k.startswith("_") and k != "_id" for k in funded)


def test_rings_need_more_than_one_hop() -> None:
    w = datagen.generate()
    final = {a["application_id"]: a for a in datagen.applications_as_of(w, w.as_of)}
    for ring in w.rings:
        members = [final[a] for a in ring]
        assert len({m["borrower"]["borrower_id"] for m in members}) == len(members)
        for kind in ("phone", "device", "address"):
            values = {
                m["contact"]["phone"]
                if kind == "phone"
                else m["device_id"]
                if kind == "device"
                else m["address"]["line1"]
                for m in members
            }
            assert len(values) > 1, f"one {kind} links the whole ring {ring}; it should need several hops"


def test_payments_belong_to_funded_loans_and_respect_as_of() -> None:
    w = datagen.generate(n_borrowers=500)
    loans = {a["loan"]["loan_id"]: a["loan"] for a in w.applications if a.get("loan")}
    for p in w.payments:
        assert p["loan_id"] in loans
        assert p["event_time"] <= w.as_of
        assert p["ingested_at"] >= p["event_time"]
        assert p["event_day"] == p["event_time"].date()
        assert p["amount_cents"] == round(loans[p["loan_id"]]["instalment"] * 100)
    ids = [p["event_id"] for p in w.payments]
    assert len(ids) == len(set(ids))


def test_drift_is_present_on_purpose() -> None:
    w = datagen.generate()
    final = datagen.applications_as_of(w, w.as_of)
    strings = [a for a in final if isinstance(a["requested_amount"], str)]
    assert strings and all(a["channel"] == "broker" and a["schema_version"] == 2 for a in strings)
    assert all(a["submitted_at"] >= datagen.DRIFT_AMOUNT_AS_STRING_FROM for a in strings)
    with_consent = [a for a in final if "marketing_consent" in a]
    assert with_consent and all(a["submitted_at"] >= datagen.DRIFT_NEW_FIELD_FROM for a in with_consent)


def test_instalment_formula() -> None:
    assert datagen.instalment_amount(12_000, 0.0, 12) == 1000.0
    # 10,000 over 12 months at 12% a year: the textbook answer is 888.49
    assert datagen.instalment_amount(10_000, 0.12, 12) == 888.49


def test_payments_ingested_by() -> None:
    w = datagen.generate(n_borrowers=300)
    t = datetime(2025, 6, 30, tzinfo=UTC)
    got = datagen.payments_ingested_by(w, t)
    assert got and all(p["ingested_at"] <= t for p in got)
