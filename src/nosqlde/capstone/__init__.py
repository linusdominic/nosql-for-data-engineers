"""The capstone: a fictional lender's operational NoSQL systems, and the pipelines that
turn them into a Parquet lake and an analytics model.

    sources.py  - the operational side: what the lender's applications write
    extract.py  - incremental, re-runnable extracts into lake/capstone/raw
    model.py    - DuckDB models: curated tables, fct_loan, mart_delinquency
    reconcile.py- source versus lake, with counts and checksums
    pipeline.py - runs the whole story and prints a summary (`make capstone`)
"""
