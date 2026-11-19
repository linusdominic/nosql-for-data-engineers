"""`make capstone`: the whole story, start to finish, with a printed summary.

1. Reset all four operational systems and the capstone lake.
2. Move the sources to 2025-06-20 and run the pipeline (initial load).
3. Move the sources to 2025-12-31 (new and changed applications, three erasures,
   six months of payments including late and duplicate deliveries) and run the
   pipeline again (incremental).
4. Run it a third time with no source changes: nothing new may be written.
5. Backfill March 2025 payments: rewrite 31 day partitions; nothing may change.
6. Build the DuckDB model (fct_loan, mart_delinquency) and reconcile every source
   against it.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb

from nosqlde import clients, datagen, lake
from nosqlde.capstone import extract, model, reconcile
from nosqlde.capstone.sources import SourceChanges, Sources
from nosqlde.config import SETTINGS
from nosqlde.console import heading, say, step, table
from nosqlde.recon import Fingerprint, fingerprint

T1 = datetime(2025, 6, 20, 23, 59, 59, tzinfo=UTC)


@dataclass
class RunResult:
    name: str
    as_of: datetime
    mongo: extract.MongoResult
    cassandra: extract.CassandraResult
    neo4j_edges: int
    seconds: float


def run_pipeline(src: Sources, root: Path, name: str, as_of: datetime) -> RunResult:
    start = time.perf_counter()
    state = lake.State(root / "_state" / "state.json")
    m = extract.extract_mongo(src, root, state, as_of)
    c = extract.extract_cassandra(src, root, state, as_of)
    n = extract.extract_neo4j(src, root, as_of)
    result = RunResult(name, as_of, m, c, n, time.perf_counter() - start)
    runs = state.get("runs", [])
    runs.append({"name": name, "as_of": as_of.isoformat(), "mongo_rows": m.rows, "cassandra_rows": c.rows})
    state.set("runs", runs)
    lake.write_json(
        root / "_manifests" / f"{len(runs):03d}-{name.replace(' ', '_')}.json",
        {
            "run": name, "as_of": as_of, "seconds": round(result.seconds, 3),
            "mongo": {"window": m.window, "rows": m.rows, "deleted_detected": m.deleted, "file": m.file,
                      "drift": m.report.lines()},
            "cassandra": {"days": c.days, "partitions": c.partitions, "rows": c.rows},
            "neo4j": {"edges": n},
        },
    )  # fmt: skip
    return result


def raw_fingerprints(root: Path) -> dict[str, Fingerprint]:
    """Fingerprints of the raw layer itself (not the deduplicated model)."""
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    out = {}
    out["raw mongo application rows"] = fingerprint(
        con.execute(
            f"SELECT application_id, updated_at FROM '{root}/raw/mongo/applications/*.parquet'"
        ).fetchall()
    )
    out["raw cassandra payment rows"] = fingerprint(
        con.execute(
            f"SELECT event_id, amount_cents FROM read_parquet('{root}/raw/cassandra/payment_events/*/*.parquet')"
        ).fetchall()
    )
    return out


def _changes_row(name: str, ch: SourceChanges) -> list[Any]:
    i = ch.ingest
    return [
        name, ch.as_of.date(), ch.applications_inserted, ch.applications_updated,
        len(ch.applications_deleted), i.delivered, i.redelivered, i.duplicates_skipped, i.written,
    ]  # fmt: skip


def _run_row(r: RunResult) -> list[Any]:
    days = f"{r.cassandra.days[0]}..{r.cassandra.days[1]}" if r.cassandra.days else "-"
    return [
        r.name, r.mongo.rows, r.mongo.deleted, days, r.cassandra.partitions,
        r.cassandra.rows, r.neo4j_edges, f"{r.seconds:.2f}",
    ]  # fmt: skip


def main(scale: int = 2_000) -> int:
    started = time.perf_counter()
    heading("Capstone: Larkspur Lending (fictional) -> Parquet lake -> DuckDB")
    root = SETTINGS.lake_dir / "capstone"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    world = datagen.generate(seed=42, n_borrowers=scale)
    t2 = world.as_of
    src = Sources(
        mongo=clients.mongo(),
        cassandra=clients.cassandra(),
        redis=clients.redis_client(7),
        neo4j=clients.neo4j(),
        world=world,
    )

    step("1", "Reset the operational systems")
    src.reset()
    say(f"world: seed 42, {scale} borrowers; source snapshots at {T1.date()} and {t2.date()}")

    step("2", f"Sources as of {T1.date()}, then the initial pipeline run")
    ch1 = src.advance_to(T1)
    run1 = run_pipeline(src, root, "run 1 initial", T1)
    say("drift report for the run 1 application batch:")
    for line in run1.mongo.report.lines():
        say(f"  {line}")

    step("3", f"Sources move to {t2.date()} (3 erasures), incremental run")
    ch2 = src.advance_to(t2, erase=3)
    run2 = run_pipeline(src, root, "run 2 incremental", t2)
    say(f"erased in the source: {ch2.applications_deleted}; detected by the key scan: {run2.mongo.deleted}")
    late = sum(1 for p in world.payments if p["event_day"] < T1.date() and T1 < p["ingested_at"] <= t2)
    say(
        f"late events (paid before {T1.date()}, arrived after run 1): {late}; "
        f"run 2 re-read {extract.LOOKBACK_DAYS} days before its watermark to pick them up"
    )

    step("4", "Re-run with no source changes")
    before = raw_fingerprints(root)
    run3 = run_pipeline(src, root, "run 3 re-run", t2)
    after = raw_fingerprints(root)
    for k in before:
        say(
            f"{k}: before {before[k]} | after {after[k]} | {'unchanged' if before[k] == after[k] else 'CHANGED'}"
        )

    step("5", "Backfill March 2025 payments")
    bf_start = time.perf_counter()
    backfill = extract.extract_cassandra_days(src, root, date(2025, 3, 1), date(2025, 3, 31))
    after_bf = raw_fingerprints(root)
    say(
        f"rewrote {backfill.partitions} day partitions ({backfill.rows} rows) in "
        f"{time.perf_counter() - bf_start:.2f}s"
    )
    for k in after:
        say(f"{k}: {'unchanged' if after[k] == after_bf[k] else 'CHANGED'} ({after_bf[k]})")

    step("6", "Build the model and reconcile")
    counts = model.build(root, t2)
    table([[k, v] for k, v in counts.items()], ["model table", "rows"])
    results = reconcile.run_all(src, root)
    for r in results:
        say(r.line())

    heading("Summary")
    say("source changes applied before each run:")
    table(
        [_changes_row("before run 1", ch1), _changes_row("before run 2", ch2)],
        ["", "as_of", "apps new", "apps changed", "apps erased", "stream deliveries",
         "redelivered", "dups skipped", "events written"],
    )  # fmt: skip
    say("pipeline runs:")
    table(
        [_run_row(r) for r in (run1, run2, run3)],
        [
            "run",
            "mongo rows",
            "deletes found",
            "cassandra days",
            "partitions",
            "payment rows",
            "neo4j edges",
            "seconds",
        ],
    )
    con = model.connect(root)
    say(f"delinquency at {t2.date()} (from fct_loan):")
    buckets = con.execute(
        "SELECT dpd_bucket, count(*), round(sum(arrears), 2) FROM fct_loan "
        "GROUP BY dpd_bucket ORDER BY min(days_past_due)"
    ).fetchall()
    table(buckets, ["dpd_bucket", "loans", "arrears"])
    ring = con.execute(
        "SELECT ring_flag, count(*), round(avg((days_past_due >= 30)::INT), 4) FROM fct_loan GROUP BY ALL ORDER BY 1"
    ).fetchall()
    table(ring, ["ring_flag", "loans", "share 30+ dpd"])
    con.close()
    size = lake.dir_size(root)
    files = sum(1 for p in root.rglob("*.parquet"))
    say(f"lake: {root}/ holds {files} Parquet files, {size / 1_048_576:.1f} MB (including warehouse.duckdb)")
    ok = all(r.ok for r in results) and before == after == after_bf and run3.mongo.rows == 0
    say(
        f"reconciliation: {sum(r.ok for r in results)}/{len(results)} OK; re-run and backfill idempotent: {before == after == after_bf}"
    )
    say(f"capstone finished in {time.perf_counter() - started:.1f}s: {'PASS' if ok else 'FAIL'}")
    src.mongo.close()
    src.cassandra.cluster.shutdown()
    src.neo4j.close()
    return 0 if ok else 1
