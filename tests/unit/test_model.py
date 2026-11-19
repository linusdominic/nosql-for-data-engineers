"""The capstone's DuckDB model on a tiny hand-made lake (no databases needed)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb

from nosqlde import lake
from nosqlde.capstone import extract, model

AS_OF = datetime(2025, 5, 20, 23, 59, 59, tzinfo=UTC)


def _app(app_id: str, updated: datetime, status: str, loan: bool, borrower: str) -> dict[str, object]:
    row: dict[str, object] = {c: None for c in extract.APPLICATION_SCHEMA}
    row.update(
        application_id=app_id, borrower__borrower_id=borrower, product="auto", channel="web",
        requested_amount=Decimal("1200.00"), term_months=12, status=status, updated_at=updated,
        submitted_at=datetime(2025, 1, 1, tzinfo=UTC),
    )  # fmt: skip
    if loan:
        row.update(
            loan__loan_id=f"L{app_id[1:]}", loan__principal=Decimal("1200.00"), loan__annual_rate=0.1,
            loan__term_months=12, loan__instalment=Decimal("100.00"),
            loan__originated_at=datetime(2025, 1, 10, 9, tzinfo=UTC),
        )  # fmt: skip
    row["_rescued"] = None
    return row


def build_lake(root: Path) -> None:
    schema = lake.arrow_schema(extract.APPLICATION_SCHEMA, rescued=True)
    t0 = datetime(2025, 1, 5, tzinfo=UTC)
    t1 = datetime(2025, 1, 10, 9, tzinfo=UTC)
    # Batch 1 has A1 approved; batch 2 has the funded version of A1, plus A2 and A3.
    lake.write_parquet(
        [_app("A1", t0, "approved", False, "B1")], root / "raw/mongo/applications/batch=1.parquet", schema
    )
    lake.write_parquet(
        [
            _app("A1", t1, "funded", True, "B1"),
            _app("A2", t1, "funded", True, "B2"),
            _app("A3", t1, "withdrawn", False, "B3"),
        ],
        root / "raw/mongo/applications/batch=2.parquet",
        schema,
    )
    lake.write_parquet(
        [{"application_id": "A3", "detected_at": t1}],
        root / "raw/mongo/applications_deleted/detected=1.parquet",
        lake.arrow_schema(extract.DELETED_SCHEMA),
    )
    pay = lake.arrow_schema(extract.PAYMENT_SCHEMA)
    # L1 pays instalments 1 and 2 (due Feb 10 and Mar 10); L2 pays 1..4 (all due so far).
    events = [("L1", 1, date(2025, 2, 10)), ("L1", 2, date(2025, 3, 11))] + [
        ("L2", k, date(2025, 1 + k, 9)) for k in range(1, 5)
    ]
    for i, (loan, k, day) in enumerate(events):
        t = datetime(day.year, day.month, day.day, 23, 30, tzinfo=UTC)  # late evening UTC on purpose
        lake.write_parquet(
            [
                {
                    "event_id": f"E{i}",
                    "loan_id": loan,
                    "event_time": t,
                    "event_day": day,
                    "ingested_at": t,
                    "instalment_no": k,
                    "amount_cents": 10_000,
                    "method": "card",
                }
            ],
            root / f"raw/cassandra/payment_events/event_day={day.isoformat()}/part-{i}.parquet",
            pay,
        )
    lake.write_parquet(
        [
            {"application_id": a, "borrower_id": b, "kind": "USES_PHONE", "value": "p"}
            for a, b in (("A1", "B1"), ("A2", "B2"))
        ],
        root / "raw/neo4j/identity_edges/snapshot=2025-05-20/part-0.parquet",
        lake.arrow_schema(extract.EDGE_SCHEMA),
    )


def test_model_builds_and_computes_days_past_due(tmp_path: Path) -> None:
    build_lake(tmp_path)
    counts = model.build(tmp_path, AS_OF)
    assert counts["applications_current"] == 2  # A3 was deleted in the source
    assert counts["loans"] == 2 and counts["payment_events"] == 6 and counts["fct_loan"] == 2
    con = duckdb.connect(str(tmp_path / "warehouse.duckdb"))
    rows = {r[0]: r[1:] for r in con.execute(
        "SELECT loan_id, instalments_due, instalments_paid, days_past_due, dpd_bucket, arrears FROM fct_loan"
    ).fetchall()}  # fmt: skip
    # Due dates: Feb 10, Mar 10, Apr 10, May 10 -> 4 due by May 20.
    # L1 paid 2, so instalment 3 (due Apr 10) is unpaid: 40 days past due.
    assert rows["L1"] == (4, 2, 40, "30-59", Decimal("200.00"))
    assert rows["L2"] == (4, 4, 0, "current", Decimal("0.00"))
    status = con.execute("SELECT status FROM applications_current WHERE application_id = 'A1'").fetchone()
    assert status == ("funded",)  # the latest version wins
    mart = con.execute("SELECT loans, dpd_30_59, current, rate_30_plus FROM mart_delinquency").fetchall()
    assert mart == [(2, 1, 1, 0.5)]
    assert (tmp_path / "marts" / "fct_loan.parquet").exists()


def test_model_is_a_pure_function_of_the_lake(tmp_path: Path) -> None:
    build_lake(tmp_path)
    model.build(tmp_path, AS_OF)
    first = (
        duckdb.connect(str(tmp_path / "warehouse.duckdb"))
        .execute("SELECT * FROM fct_loan ORDER BY 1")
        .fetchall()
    )
    model.build(tmp_path, AS_OF)
    again = (
        duckdb.connect(str(tmp_path / "warehouse.duckdb"))
        .execute("SELECT * FROM fct_loan ORDER BY 1")
        .fetchall()
    )
    assert first == again


def test_identity_groups_flag_rings(tmp_path: Path) -> None:
    build_lake(tmp_path)
    model.build(tmp_path, AS_OF)
    flags = (
        duckdb.connect(str(tmp_path / "warehouse.duckdb"))
        .execute("SELECT loan_id, identity_group_borrowers, ring_flag FROM fct_loan ORDER BY 1")
        .fetchall()
    )
    assert flags == [
        ("L1", 2, False),
        ("L2", 2, False),
    ]  # 2 borrowers share a phone: below the threshold of 3
