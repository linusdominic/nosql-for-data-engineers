# 0. Setup and how to use this guide

Time: about 20 minutes, most of it downloading container images.

## What you need

| Tool | Why | Check it with |
|---|---|---|
| Docker Desktop (or Docker Engine with Compose v2) | runs the databases | `docker compose version` |
| [uv](https://docs.astral.sh/uv/) | installs Python 3.12 and the pinned libraries | `uv --version` |
| `make` and `git` | run the steps, clone the repo | `make --version` |
| About 4 GB of free disk | the five images add up to about 3.7 GB | `docker system df` |
| About 5 GB of memory for Docker | only for the capstone, which runs four databases at once | Docker Desktop > Settings > Resources |

You do not need to install Python yourself: `uv` downloads Python 3.12 into the project.
You do not need any cloud account: DynamoDB runs locally as DynamoDB Local.

## Install

```bash
git clone https://github.com/linusdominic/nosql-for-data-engineers.git
cd nosql-for-data-engineers
make setup
```

`make setup` runs `uv sync --python 3.12`, which creates `.venv/` and installs the 49
packages pinned in `uv.lock` (version 0.4.0, whose lesson studio has a web server and a
Markdown reader for this guide). On the author's machine (Apple silicon, macOS), with a
fresh environment but uv's download cache already warm, it took under a second
(`Installed 49 packages in 87ms`). The first run on a new machine also downloads
Python 3.12 and the packages, which depends on your network.

Check that the toolchain works without any database:

```bash
make datagen
```

```text
borrowers                     2000
applications                  2393
funded_loans                  1478
payment_events               11465
late_arriving_events           340
fraud_rings                      8
ring_applications               32
households                      60
amount_as_string_docs          206
missing_employment_docs        110
```

These are the rows of the synthetic lender every chapter uses (more on it below). If
you see exactly these numbers, your setup is producing the same data as the guide.

## How each chapter works

Every database chapter follows the same loop:

```bash
make up-02      # start only the database this chapter needs, wait until it is healthy
make lab-02     # run the lab: it prints every step and its result
# read guide/02-..., then edit exercises/ch02_mongodb.py
make check-02   # check your answers against the running database
make down       # stop and delete the containers (and their data)
```

- **Labs** live in `src/nosqlde/labs/`. Each one drops and recreates its own database,
  keyspace or table first, so you can run it as often as you like. The guide quotes the
  lab's real output next to each step.
- **Exercises** live in `exercises/`. Each file has functions that raise
  `NotImplementedError`, with a docstring that says exactly what to build.
- **Checks** (`make check-NN`) import your file and run it against the live database.
  Before you start, every exercise fails with a clear message:

  ```text
  Checking exercises/ch02_mongodb.py
    FAIL  2.1 explode_documents: not implemented yet (the function still raises NotImplementedError)
    FAIL  2.2 approval_rate_pipeline: not implemented yet (the function still raises NotImplementedError)
    FAIL  2.3 extract_since: not implemented yet (the function still raises NotImplementedError)
    FAIL  2.4 read_changes_after: not implemented yet (the function still raises NotImplementedError)

  Chapter 2 (MongoDB): 0/4 passed (checked exercises/ch02_mongodb.py)
  Edit the file above and run the check again. Stuck? Compare with solutions/.
  ```

  `make` then prints an error line such as `make: *** [check-02] Error 1` (the wording
  varies with the make version): the check exits with a non-zero
  status while any exercise fails, so scripts and CI can tell. That is expected.
  When an answer is wrong, the check says what it expected and what it got. When your
  code raises, it names the file and line.
- **Solutions** live in `solutions/`. `make check-02 SOLUTIONS=1` runs the same check
  against them. Try the exercise first; reading a solution is most useful after you have
  a version of your own to compare.

Chapters 1 and 8 are quizzes (`make check-01`, `make check-08`) and need no database.
Chapter 7 is the capstone (`make capstone`).

## The lesson studio: the chapters in a browser, with live consoles

The same loop works in a browser. Start the databases a chapter needs, then the studio:

```bash
make up-02          # or make up-capstone up-05 for every database
make studio         # prints http://127.0.0.1:8790/?token=...; open that address
```

Each chapter becomes a lesson with steps. A step has a few paragraphs, a **Read this
section** link that opens the section of the guide it comes from inside the studio,
"Run this" examples that load into the console and run with one click, and exercises. The console on the right talks to the real database
in its own language: mongosh for MongoDB (a subset, interpreted in Python), redis-cli
syntax for Redis, CQL for Cassandra (with `TRACING ON` and `CONSISTENCY`), PartiQL or a
JSON API mode for DynamoDB Local, Cypher for Neo4j, and SQL over the lake for DuckDB.
Ctrl+Enter (Cmd+Enter on a Mac) runs it; Up and Down walk the history.

How to use it next to the chapters:

- **Read the chapter section first, then do its step.** The studio keeps the prose short
  on purpose; the guide has the explanation and the lab output the studio's numbers match.
  **Read** at the top of the studio shows every chapter of this guide, with its diagrams
  and a table of contents; a database statement in it has **Open in console**, which
  loads it into the right console for you to run. `/` searches every chapter.
- **Press Prepare data once per chapter.** It loads that chapter's data with the lab's
  own code and the seeded generator, into names of its own (database `larkspur_studio`,
  Redis database 5, keyspace `larkspur_studio`, table `larkspur_studio`), so a lab or a
  check never disturbs it and your counts match the guide. Press it again whenever you
  want a clean start. Neo4j Community has a single database, so chapter 6's Prepare, its
  lab and check, and the capstone all reset the same graph.
- **Check my answer** runs your statement and the reference solution and compares the
  results (or the state the database is left in, for writes). It says PASS or FAIL, with
  what was expected and what you got. Up to three hints open one at a time; the solution
  opens after your first attempt.
- **Chapter 7** runs the capstone from the browser (the same command as `make capstone`),
  shows each stage as it streams, then has exercises over the lake in DuckDB. Chapters 1
  and 8 are their quizzes.
- **Run the whole lab** streams `make lab-NN` into the page, for the full step-by-step
  output the guide quotes.

Your progress is kept in `.studio/progress.json` (ignored by git). The studio listens on
127.0.0.1 only and needs the token from the printed address; the token changes every
time it starts. `make studio STUDIO_PORT=8791` picks another port. Stop it with Ctrl+C,
and stop the databases with `make down` as usual. The offline
[explorer](https://linusdominic.github.io/nosql-for-data-engineers/explorer/) is a
separate companion with simulations and needs no database.

## The data: Larkspur Lending (fictional)

All data comes from `src/nosqlde/datagen.py`, a seeded generator for an invented consumer
lender. Every name, employer, street, town, phone number and amount is made up. Phone
numbers use the `+999` prefix, which no country has; emails use `example.com`, a domain
reserved for documentation; employers carry "(fictional)" in their name.

The generator is deterministic: `generate(seed=42)` returns the same borrowers,
applications, payments and fraud rings on every machine. That is why the guide can quote
exact counts and why your output should match it, apart from timings.

What is in it, and which chapter uses it:

| Entity | Shape | Used in |
|---|---|---|
| applications | one nested document each: borrower snapshot, contact, address, decision, uploaded documents, and the loan once funded | chapters 2, 5, 6, 7 |
| payment events | one per instalment received, with `event_time` (paid) and `ingested_at` (arrived) | chapters 3, 4, 5, 7 |
| identity links | phones, devices and addresses shared between applications, including 8 planted fraud rings and 60 households | chapters 6, 7 |

It also contains deliberate problems, because a data engineer's job is mostly handling them:
amounts that arrive as strings from one channel after 1 April 2025, a field that appears in
May, a sub-document that some front ends never send, payment events that arrive days late,
and (in the capstone) duplicate deliveries and hard deletes.

## Ports

The containers listen on uncommon host ports so they do not clash with other projects:

| Database | Host port | Compose profile |
|---|---|---|
| MongoDB 8.0.38 | 27117 | `ch02`, `capstone` |
| Redis 8.2.11 | 6479 | `ch03`, `capstone` |
| Cassandra 5.0.9 | 9142 | `ch04`, `capstone` |
| DynamoDB Local 3.3.2 | 8100 | `ch05` |
| Neo4j 5.26.33 Community | 7787 (Bolt), 7574 (browser) | `ch06`, `capstone` |

If one is taken, change the left-hand number in `docker-compose.yml` and export the
matching variable from `src/nosqlde/config.py`. Only Cassandra has a port variable
(`export NOSQLDE_CASSANDRA_PORT=9242`); the others take a full address:
`NOSQLDE_MONGO_URI`, `NOSQLDE_REDIS_URL`, `NOSQLDE_DYNAMODB_ENDPOINT` and
`NOSQLDE_NEO4J_URI`. Keep `?directConnection=true` on the MongoDB one, for example
`export NOSQLDE_MONGO_URI="mongodb://localhost:27118/?directConnection=true"`.

## Memory

Each service has a memory cap in `docker-compose.yml`. Observed use on the author's
machine with every service running, from `docker stats --no-stream`:

| Container | Observed | Cap |
|---|---|---|
| cassandra | 1.32 GiB | 2 GiB (heap capped at 512 MB) |
| neo4j | 720 MiB | 1.25 GiB (heap 512 MB, page cache 128 MB) |
| mongo | 433 MiB | 1 GiB (WiredTiger cache 0.25 GB) |
| dynamodb | 301 MiB | 512 MiB (JVM `-Xmx256m`) |
| redis | 16 MiB | 256 MiB |

You rarely need more than one at a time: `make down` between chapters keeps it that way.

## What is not verified

- The guide was run end to end on one machine: macOS on Apple silicon, Docker Desktop
  with about 8 GB for containers. Linux was exercised only through the CI workflow
  definition, which has not been run by the author (see the README). Windows was not tried.
- Download times depend on your network and are not quoted.
- The lesson studio was tried in Google Chrome only (157, headless, at 1440, 1280 and
  1024 pixels wide and at phone width); the README lists its limits.
