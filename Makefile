# NoSQL for data engineers: one target per step of the guide.
# Run `make help` for the list. Chapter numbers are two digits: 01 .. 08.

SHELL := /bin/bash
COMPOSE ?= docker compose
UV ?= uv
SOLUTIONS ?=
CHECK_FLAGS := $(if $(SOLUTIONS),--solutions,)
RUN := $(UV) run --python 3.12
# Every profile, listed explicitly (older Compose versions do not accept --profile "*").
ALL_PROFILES := --profile ch02 --profile ch03 --profile ch04 --profile ch05 --profile ch06 --profile capstone

.DEFAULT_GOAL := help
.PHONY: help setup datagen ps logs down clean test test-unit test-integration lint format capstone \
        up-02 up-03 up-04 up-05 up-06 up-capstone explorer explorer-data
# lab-% and check-% are pattern rules; make skips pattern rules for .PHONY targets,
# so they are deliberately not listed above.

help: ## Show this list
	@grep -hE '^[a-zA-Z0-9_%-]+:.*## ' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN {FS = ":.*## "}; {printf "  make %-18s %s\n", $$1, $$2}'
	@echo "  make check-NN SOLUTIONS=1  check the reference solutions instead of your answers"

setup: ## Install Python 3.12 and the pinned dependencies with uv
	$(UV) sync --python 3.12
	@echo; echo "Setup done. Next: read guide/00-setup.md, then run 'make check-01'."

datagen: ## Print the synthetic data summary (no database needed)
	$(RUN) nosqlde datagen

# ---- containers -----------------------------------------------------------------
up-02: ## Start MongoDB (chapter 2)
	$(COMPOSE) --profile ch02 up -d --wait
up-03: ## Start Redis (chapter 3)
	$(COMPOSE) --profile ch03 up -d --wait
up-04: ## Start Cassandra (chapter 4, takes about a minute)
	$(COMPOSE) --profile ch04 up -d --wait
up-05: ## Start DynamoDB Local (chapter 5)
	$(COMPOSE) --profile ch05 up -d --wait
up-06: ## Start Neo4j (chapter 6)
	$(COMPOSE) --profile ch06 up -d --wait
up-capstone: ## Start MongoDB, Redis, Cassandra and Neo4j (chapter 7)
	$(COMPOSE) --profile capstone up -d --wait

ps: ## Show the guide's containers and their health
	$(COMPOSE) $(ALL_PROFILES) ps
logs: ## Show the last 50 log lines of every container
	$(COMPOSE) $(ALL_PROFILES) logs --tail 50

down: ## Stop and remove every container of this guide, with its data
	$(COMPOSE) $(ALL_PROFILES) down -v --remove-orphans

# ---- labs and checks -------------------------------------------------------------
lab-%: ## Run a chapter's lab, e.g. make lab-02
	$(RUN) nosqlde lab $*

check-%: ## Check your exercise answers, e.g. make check-02
	$(RUN) nosqlde check $* $(CHECK_FLAGS)

capstone: up-capstone ## Run the end-to-end capstone pipeline (starts its containers)
	$(RUN) nosqlde capstone

# ---- explorer --------------------------------------------------------------------
EXPLORER_PORT ?= 8099

explorer: ## Serve the interactive explorer (docs/explorer) on localhost
	@echo "NoSQL explorer: http://localhost:$(EXPLORER_PORT)/explorer/  (Ctrl+C to stop)"
	@echo "No server needed either: open docs/explorer/index.html in a browser."
	python3 -m http.server -d docs -b 127.0.0.1 $(EXPLORER_PORT)

explorer-data: ## Rebuild docs/explorer/data.js from the generator and the recorded lab output
	$(RUN) python tools/build_explorer_data.py

# ---- quality ---------------------------------------------------------------------
test: test-unit ## Unit tests (no database needed)

test-unit:
	$(RUN) pytest tests/unit -q

test-integration: ## Integration tests (needs: make up-capstone up-03 up-05)
	$(RUN) pytest tests/integration -q

lint: ## ruff, ruff format --check, mypy --strict
	$(RUN) ruff check .
	$(RUN) ruff format --check .
	$(RUN) mypy

format: ## Apply ruff formatting and safe fixes
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

clean: ## Remove lab output and tool caches (not the containers: use make down)
	rm -rf lake .pytest_cache .mypy_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
