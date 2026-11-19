"""Build the analytics model in DuckDB from the raw Parquet lake.

raw (append-only batches, day partitions, snapshots)
  -> curated (one current row per entity: dedup, deletes applied)
  -> marts (fct_loan: one row per loan; mart_delinquency: one row per cohort)

Every table is rebuilt from raw with CREATE OR REPLACE, so the model is a pure
function of the lake: running it twice gives the same result.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import duckdb

from nosqlde import graph, lake

CURATED_SQL = """
-- Every extract batch is kept. The current state is the latest version per key.
CREATE OR REPLACE TABLE applications_current AS
SELECT * EXCLUDE (version_rank)
FROM (
    SELECT *, row_number() OVER (PARTITION BY application_id ORDER BY updated_at DESC) AS version_rank
    FROM read_parquet('{root}/raw/mongo/applications/*.parquet', union_by_name = true)
)
WHERE version_rank = 1
  AND application_id NOT IN (SELECT application_id FROM applications_deleted);

CREATE OR REPLACE TABLE loans AS
SELECT loan__loan_id AS loan_id, application_id, borrower__borrower_id AS borrower_id,
       product, channel, loan__principal AS principal, loan__annual_rate AS annual_rate,
       loan__term_months AS term_months, loan__instalment AS instalment,
       loan__originated_at AS originated_at
FROM applications_current
WHERE loan__loan_id IS NOT NULL;

-- Day partitions are overwritten on re-extract, so they hold no duplicates; the
-- QUALIFY is a cheap guard in case two files ever overlap.
CREATE OR REPLACE TABLE payment_events AS
SELECT * EXCLUDE (event_day), CAST(event_day AS DATE) AS event_day
FROM read_parquet('{root}/raw/cassandra/payment_events/*/*.parquet', hive_partitioning = true)
QUALIFY row_number() OVER (PARTITION BY event_id ORDER BY ingested_at) = 1;

CREATE OR REPLACE TABLE identity_edges AS
SELECT application_id, borrower_id, kind, value
FROM read_parquet('{root}/raw/neo4j/identity_edges/*/*.parquet', hive_partitioning = true)
WHERE snapshot = (SELECT max(snapshot) FROM read_parquet('{root}/raw/neo4j/identity_edges/*/*.parquet', hive_partitioning = true));
"""

FCT_LOAN_SQL = """
CREATE OR REPLACE MACRO due_date(originated, k) AS
    CAST(date_trunc('month', CAST(originated AS DATE)) + to_months(k)
         + to_days(least(day(CAST(originated AS DATE)), 28) - 1) AS DATE);

CREATE OR REPLACE TABLE fct_loan AS
WITH paid AS (
    SELECT loan_id, count(*) AS instalments_paid,
           CAST(sum(amount_cents) / 100 AS DECIMAL(18, 2)) AS amount_paid,  -- money stays DECIMAL
           max(event_time) AS last_payment_at
    FROM payment_events
    WHERE event_time <= TIMESTAMPTZ '{as_of}'
    GROUP BY loan_id
),
base AS (
    SELECT l.*,
           date_trunc('month', CAST(l.originated_at AS DATE)) AS origination_month,
           coalesce(p.instalments_paid, 0) AS instalments_paid,
           coalesce(p.amount_paid, 0) AS amount_paid_to_date,
           p.last_payment_at,
           -- instalments that have fallen due by as_of
           (SELECT count(*) FROM range(1, l.term_months + 1) r(k)
             WHERE due_date(l.originated_at, r.k) <= DATE '{as_of_date}') AS instalments_due
    FROM loans l LEFT JOIN paid p USING (loan_id)
),
dpd AS (
    SELECT *,
           CASE WHEN instalments_paid < instalments_due
                THEN DATE '{as_of_date}' - due_date(originated_at, instalments_paid + 1)
                ELSE 0 END AS days_past_due
    FROM base
)
SELECT d.loan_id, d.application_id, d.borrower_id, d.product, d.channel,
       CAST(d.origination_month AS DATE) AS origination_month,
       d.principal, d.annual_rate, d.term_months, d.instalment,
       d.instalments_due, d.instalments_paid,
       round(d.instalments_due * d.instalment, 2) AS amount_due_to_date,
       round(d.amount_paid_to_date, 2) AS amount_paid_to_date,
       round(greatest(d.instalments_due * d.instalment - d.amount_paid_to_date, 0), 2) AS arrears,
       d.last_payment_at, d.days_past_due,
       CASE WHEN d.days_past_due = 0 THEN 'current'
            WHEN d.days_past_due < 30 THEN '1-29'
            WHEN d.days_past_due < 60 THEN '30-59'
            WHEN d.days_past_due < 90 THEN '60-89'
            ELSE '90+' END AS dpd_bucket,
       coalesce(g.group_borrowers, 1) AS identity_group_borrowers,
       coalesce(g.group_borrowers, 1) >= 3 AS ring_flag
FROM dpd d LEFT JOIN identity_groups g USING (application_id)
ORDER BY d.loan_id;

CREATE OR REPLACE TABLE mart_delinquency AS
SELECT origination_month, product,
       count(*) AS loans,
       sum(principal) AS principal,
       count(*) FILTER (WHERE dpd_bucket = 'current') AS current,
       count(*) FILTER (WHERE dpd_bucket = '1-29') AS dpd_1_29,
       count(*) FILTER (WHERE dpd_bucket = '30-59') AS dpd_30_59,
       count(*) FILTER (WHERE dpd_bucket = '60-89') AS dpd_60_89,
       count(*) FILTER (WHERE dpd_bucket = '90+') AS dpd_90_plus,
       round(count(*) FILTER (WHERE days_past_due >= 30) / count(*), 4) AS rate_30_plus,
       count(*) FILTER (WHERE ring_flag) AS ring_loans
FROM fct_loan
GROUP BY ALL
ORDER BY origination_month, product;
"""


def connect(root: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(root / "warehouse.duckdb"))
    # TIMESTAMPTZ values are converted to DATE in the session time zone. Without this
    # line, a payment at 23:30 UTC lands on a different day on a laptop in UTC+1.
    con.execute("SET TimeZone = 'UTC'")
    return con


def build(root: Path, as_of: datetime) -> dict[str, int]:
    con = connect(root)
    deleted_dir = root / "raw" / "mongo" / "applications_deleted"
    has_deleted = deleted_dir.exists() and any(deleted_dir.glob("*.parquet"))
    if has_deleted:
        con.execute(
            "CREATE OR REPLACE TABLE applications_deleted AS SELECT DISTINCT application_id "
            f"FROM read_parquet('{deleted_dir}/*.parquet')"
        )
    else:
        con.execute("CREATE OR REPLACE TABLE applications_deleted (application_id VARCHAR)")
    con.execute(CURATED_SQL.format(root=root))

    edges = con.execute(
        "SELECT application_id, borrower_id, kind || ':' || value FROM identity_edges"
    ).fetchall()
    borrower_of = {a: b for a, b, _ in edges}
    groups = graph.components_from_shared_keys((a, k) for a, _, k in edges)
    rows = [
        {"application_id": m, "group_id": gid, "group_borrowers": len({borrower_of[x] for x in members})}
        for gid, members in groups.items()
        for m in members
    ]
    path = root / "curated" / "identity_groups.parquet"
    lake.write_parquet(
        rows, path,
        lake.arrow_schema({"application_id": "string", "group_id": "string", "group_borrowers": "int"}),
    )  # fmt: skip
    con.execute(f"CREATE OR REPLACE TABLE identity_groups AS SELECT * FROM '{path}'")

    con.execute(FCT_LOAN_SQL.format(as_of=as_of.isoformat(), as_of_date=as_of.date().isoformat()))
    marts = root / "marts"
    marts.mkdir(parents=True, exist_ok=True)
    for name in ("fct_loan", "mart_delinquency"):
        con.execute(f"COPY {name} TO '{marts / name}.parquet' (FORMAT parquet)")
    counts = {
        name: int((con.execute(f"SELECT count(*) FROM {name}").fetchone() or (0,))[0])
        for name in (
            "applications_current",
            "loans",
            "payment_events",
            "identity_edges",
            "fct_loan",
            "mart_delinquency",
        )
    }
    con.close()
    return counts
