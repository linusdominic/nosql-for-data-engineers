# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-11-19

### Added

- Guide chapters 0 to 8: setup, why NoSQL exists, MongoDB, Redis, Cassandra, DynamoDB
  (DynamoDB Local), Neo4j, an end-to-end capstone, and a decision guide with glossary
  and review questions.
- Runnable labs for chapters 2 to 6, exercises with checks for every chapter, and
  reference solutions.
- A seeded synthetic data generator for a fictional lender (Larkspur Lending).
- Shared helpers for flattening documents, conforming schema drift, writing Parquet
  atomically, reconciling with order-independent checksums, and connected components.
- The capstone pipeline: MongoDB, Redis Streams, Cassandra and Neo4j into a Parquet lake,
  a DuckDB model (`fct_loan`, `mart_delinquency`), re-run and backfill checks, and
  source-to-lake reconciliation.
- `docker-compose.yml` with one profile per chapter and pinned images; `Makefile`;
  unit and integration tests; a GitHub Actions workflow.
