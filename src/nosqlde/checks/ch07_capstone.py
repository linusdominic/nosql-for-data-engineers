"""Check chapter 7's exercises (7.4 needs the capstone's output)."""

from __future__ import annotations

import random
from datetime import date

import duckdb

from nosqlde import checks
from nosqlde.config import SETTINGS


def run(solutions: bool = False) -> int:
    checker, answers = checks.start("Chapter 7 (capstone)", "ch07_capstone.py", solutions)

    def ex1() -> str:
        cases = {None: "current", 0: "current", 1: "1-29", 29: "1-29", 30: "30-59", 59: "30-59",
                 60: "60-89", 89: "60-89", 90: "90+", 400: "90+"}  # fmt: skip
        for days, want in cases.items():
            got = answers.dpd_bucket(days)
            assert got == want, f"dpd_bucket({days}) should be {want!r}, got {got!r}"
        try:
            answers.dpd_bucket(-1)
        except ValueError:
            pass
        else:
            raise AssertionError("dpd_bucket(-1) should raise ValueError")
        return "all bucket boundaries correct, negative input rejected"

    def ex2() -> str:
        rows = [(f"E{i}", i * 100, "2025-03-01") for i in range(500)]
        base = answers.order_independent_checksum(rows)
        assert isinstance(base, int) and 0 <= base < 2**64, (
            f"checksum must be an int in [0, 2**64), got {base!r}"
        )
        shuffled = rows[:]
        random.Random(1).shuffle(shuffled)
        assert answers.order_independent_checksum(shuffled) == base, (
            "the checksum changed when only the order changed"
        )
        changed = rows[:]
        changed[10] = ("E10", 1001, "2025-03-01")
        assert answers.order_independent_checksum(changed) != base, "a changed value must change the checksum"
        assert answers.order_independent_checksum([*rows, rows[3]]) != base, (
            "a duplicated row must change the checksum (XOR would cancel it out)"
        )
        assert answers.order_independent_checksum(rows[:-1]) != base, "a missing row must change the checksum"
        return "order-independent; detects changed, duplicated and missing rows"

    def ex3() -> str:
        go = date(2025, 1, 1)
        first = answers.days_to_extract(None, date(2025, 1, 5), 3, go)
        assert first == [date(2025, 1, d) for d in range(1, 6)], f"first run should be Jan 1..5, got {first}"
        later = answers.days_to_extract(date(2025, 3, 10), date(2025, 3, 12), 3, go)
        assert later == [date(2025, 3, d) for d in range(7, 13)], f"expected Mar 7..12, got {later}"
        early = answers.days_to_extract(date(2025, 1, 2), date(2025, 1, 2), 3, go)
        assert early == [date(2025, 1, 1), date(2025, 1, 2)], f"never before go_live; got {early}"
        return "first run, lookback window and go-live floor all correct"

    def ex4() -> str:
        path = SETTINGS.lake_dir / "capstone" / "marts" / "fct_loan.parquet"
        assert path.exists(), f"{path} not found: run `make capstone` first"
        got = duckdb.connect().execute(answers.rate_30_plus_by_product_sql(str(path))).fetchall()
        want = (
            duckdb.connect()
            .execute(
                f"""SELECT product, count(*), count(*) FILTER (WHERE days_past_due >= 30),
                       round(count(*) FILTER (WHERE days_past_due >= 30) / count(*), 4)
                FROM '{path}' GROUP BY product ORDER BY product"""
            )
            .fetchall()
        )
        assert [tuple(r) for r in got] == [tuple(r) for r in want], f"expected {want}, got {got}"
        return ", ".join(f"{p}={r}" for p, _, _, r in want)

    checker.run("7.1 dpd_bucket", ex1)
    checker.run("7.2 order_independent_checksum", ex2)
    checker.run("7.3 days_to_extract", ex3)
    checker.run("7.4 rate_30_plus_by_product_sql", ex4)
    return checker.finish()
