# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- A demo video of the lesson studio, 2 minutes 54 seconds with a quiet CC0 music bed:
  install, then chapter 2 (Prepare data, Run this, exercise 2.3 from FAIL to PASS with a
  hint), the guide beside the console, a tour of chapters 3 to 8, search and the dark
  theme. `docs/media/studio-demo.mp4`, served by GitHub Pages and linked from the README
  with a poster and a short GIF. `make demo-video` (`tools/record_demo.py`) records it
  again end to end against its own studio and progress file; it needs Chrome, ffmpeg and
  every database, and runs Playwright through `uv run --with`, outside the project's
  dependencies and outside CI.

## [0.5.0] - 2026-11-19

### Changed

- A new look for the lesson studio, inspired by the documentation sites of the guide's
  databases (notes and sources in `src/nosqlde/studio/static/DESIGN.md`). A forest green
  top bar with Lesson, Read and the chapters as underlined tabs; white reading surfaces,
  hairline borders and a near-black green dark theme designed on its own; system fonts,
  with a serif for page titles.
- Each database has its own accent, from its documentation's colour family: MongoDB
  green, Redis red, Cassandra teal blue, DynamoDB orange, Neo4j blue and DuckDB yellow
  (chapters 1 and 8 use the studio's green). It marks the console tabs, the chapter tabs
  and their progress rings, a band at the top of each lesson, the progress bar, step
  pills, exercise cards, tags, the reader's progress bar and contents, and the status
  bar's dots. Text stays in neutral ink; every accent reaches 3:1 and every text colour
  4.5:1 on the surfaces it uses, in both themes.
- Restyled: buttons (a green primary), step pills, Run this cards, exercise cards with
  state pills, PASS and FAIL panels (Expected above Got when the card is narrow), hints,
  the quiz's answers, console results with sticky table heads and a JSON tree with
  chevrons, the search dialog, toasts and the status bar (a down database shows a hollow
  red ring, a tint and its `make` command).
- The reader puts "On this page" on the right, styles blockquotes as notes, and gives
  database code blocks a rule in the console's accent. The three diagrams were
  re-rendered with the new colours.
- README screenshots retaken in the new style.

## [0.4.0] - 2026-11-19

### Added

- The guide inside the lesson studio: **Read** at the top shows chapters 0 to 8, rendered
  on the server from `guide/*.md` on each request (markdown-it-py, raw HTML escaped). A
  table of contents that follows the scroll, copy-link heading anchors, reading
  progress, previous and next chapter, search across chapters (`/`), scrollable tables,
  lab output styled as output, light highlighting, and Copy on every code block.
- **Open in console** on every database statement in the guide: tagged Cypher, CQL, SQL
  and mongosh blocks, and untagged ones whose content can only belong to one console.
  Shell and Python blocks are copy only.
- Lessons open the reader instead of GitHub: **Read this section** on each step opens
  the reader at that heading next to the console, with **Back to step**; **Read the
  chapter** and the quizzes do the same. The reader can sit next to the console or take
  the full width.
- A read-only file viewer for repository files the guide names (`src/...`,
  `exercises/...`), limited to the guide, code, exercises, solutions, tests, tools and
  docs; the studio's lesson files, which hold the solutions, are left out.
- The three mermaid diagrams as SVG, light and dark, pre-rendered by `make diagrams`
  (`tools/render_diagrams.py`) with mermaid 12.3.0 (MIT), which the tool downloads
  from npm on first use and checks against a pinned sha256. No diagram library runs in the page, so the Content-Security-Policy is
  unchanged.
- 85 unit tests: every chapter renders, every in-studio link and anchor resolves, raw
  HTML is escaped, the file viewer refuses traversal, hidden files and symlinks out,
  console detection, and every diagram has its SVGs.
- README screenshots of the reader in light and dark; the lesson screenshots retaken.

### Changed

- New dependency: markdown-it-py 4.2.0 (with mdurl 0.1.2).
- The top bar has a Lesson and Read switch and a search button; the link to the guide
  on GitHub is gone.
- The skip links focus the lesson, reader or console without changing the page's route.

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
