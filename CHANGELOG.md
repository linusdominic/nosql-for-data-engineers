# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.3.0] - 2026-11-19

### Added

- The lesson studio (`make studio`): a local web app with every chapter as a lesson and
  live consoles connected to the guide's databases. MongoDB in a mongosh-style subset
  interpreted in Python, Redis in redis-cli syntax, Cassandra in CQL with `TRACING ON` and
  `CONSISTENCY`, DynamoDB Local in PartiQL or a JSON API mode with ConsumedCapacity, Neo4j
  in Cypher with `PROFILE` summarised, and DuckDB over the Parquet lake.
- 48 checked exercises (10, 8, 9, 9 and 7 for chapters 2 to 6, and 5 over the capstone's
  lake), each with hints, a reference solution shown after an attempt, and a check that
  compares results or the data left behind; chapters 1 and 8 as quizzes from the existing
  exercise files and answer keys; chapter 7 runs the capstone from the browser and streams
  each stage.
- A "Prepare data" step per chapter that loads the lab's data with the lab's own code, in
  the studio's own database, keyspace, table and Redis database.
- Protection for a server that runs database commands from a browser: 127.0.0.1 only, a
  random token per start on every API call, Host and Origin checks against DNS rebinding,
  a strict Content-Security-Policy and no shell.
- Progress in `.studio/progress.json` (ignored by git).
- Unit tests for the mongosh parser, the result comparison, the console helpers, the
  request protection and lesson integrity; integration tests that run every exercise's
  solution and its wrong answers against the databases, and the HTTP API with the token.
- README screenshots of the studio in light and dark; a studio section in chapter 0 and
  a pointer at the top of every chapter.

### Changed

- The chapter 2, 3 and 4 labs expose their loading steps as functions (validator,
  referenced documents, May's changes, flattening and the lake write; step 3.1's keys and
  step 3.8's stream; step 4.1's tables and step 4.5's queue) so the studio reuses them.
  Their output is unchanged.
- New dependencies: fastapi 0.162.0 and uvicorn 0.54.0; httpx 0.28.1 for tests.

## [0.2.0] - 2026-11-19

### Added

- An interactive explorer in `docs/explorer/` (`make explorer`): five shapes of one loan,
  a Redis Streams consumer-group simulation, a Cassandra consistency playground, a
  DynamoDB capacity calculator, the capstone pipeline with each run's counts and a
  "which database?" walk through chapter 8. `tools/build_explorer_data.py` builds its data
  from the generator and the guide; a unit test checks every recorded number against the
  guide text.
- README figures: the capstone pipeline and its results.

### Changed

- Chapter 7 quotes the same capstone run as the README (7.4 s).

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
