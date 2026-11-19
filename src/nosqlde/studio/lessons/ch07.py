"""Chapter 7 in the studio: run the capstone from the browser, then query its lake."""

from __future__ import annotations

from nosqlde.studio.lessons.model import Example, Exercise, GuideRef, Job, Lesson, Match, Step

FCT = "'lake/capstone/marts/fct_loan.parquet'"
RAW_MONGO = "'lake/capstone/raw/mongo/applications/*.parquet'"
RAW_EVENTS = "read_parquet('lake/capstone/raw/cassandra/payment_events/*/*.parquet')"

CAPSTONE = Job(
    id="capstone",
    label="Run the capstone (make capstone)",
    argv=("capstone",),
    stages=(
        ("--- Step 1:", "Reset the four operational systems"),
        ("--- Step 2:", "Sources to 20 June, initial run"),
        ("--- Step 3:", "Six months later, incremental run"),
        ("--- Step 4:", "Re-run with no changes"),
        ("--- Step 5:", "Backfill March"),
        ("--- Step 6:", "Model and reconcile"),
        ("Summary", "Summary"),
    ),
)

LESSON = Lesson(
    id="ch07",
    number=7,
    title="Capstone: four NoSQL systems to a loan-level fact table",
    database="MongoDB, Redis, Cassandra, Neo4j, DuckDB",
    summary="Run the whole pipeline from the browser, watch each stage, then query the lake and the marts with DuckDB.",
    guide=GuideRef(7, "7. Capstone: from four NoSQL systems to a loan-level fact table"),
    consoles=("duckdb",),
    services=("mongo", "redis", "cassandra", "neo4j"),
    make_up="make up-capstone",
    jobs=(CAPSTONE,),
    steps=(
        Step(
            id="run",
            title="The story make capstone runs",
            guide=GuideRef(7, "The story `make capstone` runs"),
            prose=(
                "The capstone resets MongoDB, Redis, Cassandra and Neo4j, moves them to 20 June 2025 and runs the pipeline, moves them to 31 December (new and changed applications, three erasures, late and duplicate payments) and runs it again, then re-runs, backfills March, builds the DuckDB model and reconciles every source against it.",
                "Start the four databases with `make up-capstone`, then press **Run the capstone**: the output streams in below, stage by stage. It is the same command as `make capstone`, run by the studio with no input from the browser. It resets Neo4j, which chapter 6's lesson shares.",
                "On the author's machine the pipeline took 7.4 seconds and ended with `reconciliation: 6/6 OK; re-run and backfill idempotent: True`.",
            ),
        ),
        Step(
            id="lake",
            title="What is in the lake afterwards",
            guide=GuideRef(7, "What is in the lake afterwards"),
            prose=(
                "Raw extracts land in `lake/capstone/raw/` (Mongo batches named after their watermark window, Cassandra day partitions, Neo4j snapshots); the model writes `lake/capstone/marts/fct_loan.parquet` and `mart_delinquency.parquet`.",
                "The DuckDB console reads anything under `lake/` and nothing else. The exercises below are checked against the reference query on the lake as it is now, so run the capstone first.",
            ),
            examples=(
                Example("The fact table's columns", "duckdb", f"DESCRIBE SELECT * FROM {FCT}"),
                Example(
                    "A few loans",
                    "duckdb",
                    f"SELECT loan_id, product, instalments_due, instalments_paid, days_past_due, dpd_bucket, arrears, ring_flag\nFROM {FCT} ORDER BY loan_id LIMIT 5",
                ),
                Example(
                    "The delinquency mart",
                    "duckdb",
                    "FROM 'lake/capstone/marts/mart_delinquency.parquet' LIMIT 5",
                ),
            ),
            exercises=(
                Exercise(
                    id="ch07.versions",
                    number="7.1",
                    title="Raw keeps every version",
                    console="duckdb",
                    task=f"Over the raw Mongo batches ({RAW_MONGO}), return two numbers: `raw_rows` (every row) and `applications` (distinct `application_id`).",
                    starter=f"SELECT count(*) AS raw_rows FROM {RAW_MONGO}",
                    hints=(
                        "A glob in the path reads every batch file.",
                        "count(DISTINCT application_id)",
                        "The curated layer later keeps the latest version of each.",
                    ),
                    solution=f"SELECT count(*) AS raw_rows, count(DISTINCT application_id) AS applications FROM {RAW_MONGO}",
                    check=Match(by_position=True),
                    wrong=(
                        f"SELECT count(*) AS raw_rows, count(application_id) AS applications FROM {RAW_MONGO}",
                        f"SELECT count(DISTINCT application_id) AS applications FROM {RAW_MONGO}",
                    ),
                    explain="2,468 rows for 2,393 applications in the guide's run: 2,251 from run 1 plus 217 from run 2.",
                ),
                Exercise(
                    id="ch07.late",
                    number="7.2",
                    title="Late events the lookback picked up",
                    console="duckdb",
                    task=(
                        f"In the raw Cassandra extract ({RAW_EVENTS}), count the events paid before 20 June 2025 (`event_day`) "
                        "that reached the lender after the end of 20 June 2025 UTC (`ingested_at` after 2025-06-20 23:59:59+00)."
                    ),
                    starter=f"SELECT count(*) AS late_events FROM {RAW_EVENTS}\nWHERE event_day < DATE '2025-06-20'",
                    hints=(
                        "Two conditions: on event_day and on ingested_at.",
                        "ingested_at is a TIMESTAMP WITH TIME ZONE: compare with TIMESTAMPTZ '2025-06-20 23:59:59+00'.",
                        "These are the events run 2 re-read thanks to its 3-day lookback.",
                    ),
                    solution=(
                        f"SELECT count(*) AS late_events FROM {RAW_EVENTS}\n"
                        "WHERE event_day < DATE '2025-06-20' AND ingested_at > TIMESTAMPTZ '2025-06-20 23:59:59+00'"
                    ),
                    check=Match(by_position=True),
                    wrong=(
                        f"SELECT count(*) AS late_events FROM {RAW_EVENTS} WHERE event_day < DATE '2025-06-20'",
                        f"SELECT count(*) AS late_events FROM {RAW_EVENTS} WHERE event_day <= DATE '2025-06-20' AND ingested_at > event_time + INTERVAL 1 DAY",
                    ),
                    explain="2 in the guide's run: they landed in partitions run 1 had already extracted, so run 2 re-read 3 days before its watermark.",
                ),
            ),
        ),
        Step(
            id="model",
            title="The model",
            guide=GuideRef(7, "The model"),
            prose=(
                "`fct_loan` has one row per loan as of 31 December 2025: instalments due and paid, arrears, **days past due** (DPD, from the oldest unpaid instalment) with its bucket, and a `ring_flag` for loans in an identity group of three or more borrowers.",
                "The guide's run: 1,319 loans current, 84 in the 90+ bucket; 86% of ring-flagged loans 30+ days past due against 5% of the rest.",
            ),
            exercises=(
                Exercise(
                    id="ch07.buckets",
                    number="7.3",
                    title="Delinquency by bucket",
                    console="duckdb",
                    task=f"From {FCT}, return `dpd_bucket`, `loans` (count) and `arrears` (sum, rounded to 2 decimals), ordered from the least to the most days past due.",
                    starter=f"SELECT dpd_bucket, count(*) AS loans\nFROM {FCT}\nGROUP BY dpd_bucket ORDER BY dpd_bucket",
                    hints=(
                        "round(sum(arrears), 2) AS arrears",
                        "Ordering by the bucket name puts '1-29' before 'current'.",
                        "ORDER BY min(days_past_due)",
                    ),
                    solution=f"SELECT dpd_bucket, count(*) AS loans, round(sum(arrears), 2) AS arrears\nFROM {FCT}\nGROUP BY dpd_bucket ORDER BY min(days_past_due)",
                    check=Match(fields=("dpd_bucket", "loans", "arrears"), ordered=True),
                    wrong=(
                        f"SELECT dpd_bucket, count(*) AS loans, round(sum(arrears), 2) AS arrears FROM {FCT} GROUP BY dpd_bucket ORDER BY dpd_bucket",
                        f"SELECT dpd_bucket, count(*) AS loans, round(avg(arrears), 2) AS arrears FROM {FCT} GROUP BY dpd_bucket ORDER BY min(days_past_due)",
                    ),
                    explain="The same query make capstone prints in its summary.",
                ),
                Exercise(
                    id="ch07.rings",
                    number="7.4",
                    title="Ring-flagged loans",
                    console="duckdb",
                    task=f"From {FCT}, per `ring_flag`: `loans` (count) and `share_30_plus` (the share of loans 30 or more days past due, rounded to 4 decimals), ordered by ring_flag.",
                    starter=f"SELECT ring_flag, count(*) AS loans\nFROM {FCT}\nGROUP BY ring_flag ORDER BY ring_flag",
                    hints=(
                        "A boolean cast to INT is 0 or 1; its average is a share.",
                        "avg((days_past_due >= 30)::INT)",
                        "round(..., 4) AS share_30_plus",
                    ),
                    solution=f"SELECT ring_flag, count(*) AS loans, round(avg((days_past_due >= 30)::INT), 4) AS share_30_plus\nFROM {FCT}\nGROUP BY ring_flag ORDER BY ring_flag",
                    check=Match(fields=("ring_flag", "loans", "share_30_plus"), ordered=True),
                    wrong=(
                        f"SELECT ring_flag, count(*) AS loans, round(avg((days_past_due >= 90)::INT), 4) AS share_30_plus FROM {FCT} GROUP BY ring_flag ORDER BY ring_flag",
                        f"SELECT ring_flag, count(*) AS loans, round(avg((days_past_due >= 30)::INT), 2) AS share_30_plus FROM {FCT} GROUP BY ring_flag ORDER BY ring_flag",
                    ),
                    explain="On real data a gap like this starts an investigation; here it is how the data was generated.",
                ),
                Exercise(
                    id="ch07.products",
                    number="7.5",
                    title="30+ rate by product",
                    console="duckdb",
                    task=(
                        f"From {FCT}, per `product` (sorted): `loans`, `loans_30_plus` (days past due 30 or more) and `rate_30_plus` "
                        "(loans_30_plus / loans, rounded to 4 decimals). This is make check-07's exercise 7.4."
                    ),
                    starter=f"SELECT product, count(*) AS loans\nFROM {FCT}\nGROUP BY product ORDER BY product",
                    hints=(
                        "count(*) FILTER (WHERE days_past_due >= 30)",
                        "Divide the filtered count by count(*) inside round(..., 4).",
                        "Alias the columns exactly as the task says.",
                    ),
                    solution=(
                        f"SELECT product,\n       count(*) AS loans,\n       count(*) FILTER (WHERE days_past_due >= 30) AS loans_30_plus,\n"
                        f"       round(count(*) FILTER (WHERE days_past_due >= 30) / count(*), 4) AS rate_30_plus\nFROM {FCT}\nGROUP BY product ORDER BY product"
                    ),
                    check=Match(fields=("product", "loans", "loans_30_plus", "rate_30_plus"), ordered=True),
                    wrong=(
                        f"SELECT product, count(*) AS loans, count(*) FILTER (WHERE days_past_due >= 60) AS loans_30_plus, round(count(*) FILTER (WHERE days_past_due >= 60) / count(*), 4) AS rate_30_plus FROM {FCT} GROUP BY product ORDER BY product",
                        f"SELECT product, count(*) AS loans, count(*) FILTER (WHERE days_past_due >= 30) AS loans_30_plus, round(count(*) FILTER (WHERE days_past_due >= 30) / count(*), 2) AS rate_30_plus FROM {FCT} GROUP BY product ORDER BY product",
                    ),
                    explain="auto=0.0787, home_improvement=0.0758, personal=0.0688 in the guide's run.",
                ),
            ),
        ),
    ),
)
