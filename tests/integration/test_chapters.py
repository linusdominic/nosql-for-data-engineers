"""Run every lab, every check against the reference solutions, and the capstone.

These need the containers. Start them with
    make up-capstone up-03 up-05
(MongoDB, Redis, Cassandra, Neo4j and DynamoDB Local). A test whose database is not
reachable is skipped, not failed, so the unit-test run stays green on a laptop with
nothing running.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from nosqlde import clients
from nosqlde.capstone import pipeline

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOSQLDE_ROOT", str(ROOT))
    monkeypatch.chdir(ROOT)


def _require(connect: Callable[[], Any]) -> None:
    try:
        conn = connect()
    except clients.ServiceUnavailable as err:
        if os.environ.get("NOSQLDE_REQUIRE_SERVICES"):
            raise
        pytest.skip(str(err).splitlines()[0])
    # Look the method up on the class: MongoClient turns unknown attributes into databases.
    if hasattr(type(conn), "close"):
        conn.close()
    elif hasattr(type(conn), "shutdown"):  # a cassandra-driver Session
        conn.cluster.shutdown()


CHAPTERS = [
    ("02", "ch02_mongodb", clients.mongo),
    ("03", "ch03_redis", clients.redis_client),
    ("04", "ch04_cassandra", clients.cassandra),
    ("05", "ch05_dynamodb", clients.dynamodb_client),
    ("06", "ch06_neo4j", clients.neo4j),
]


@pytest.mark.parametrize(("number", "module", "connect"), CHAPTERS, ids=[c[0] for c in CHAPTERS])
def test_lab_runs_and_solutions_pass(
    number: str, module: str, connect: Callable[[], Any], capsys: pytest.CaptureFixture[str]
) -> None:
    _require(connect)
    importlib.import_module(f"nosqlde.labs.{module}").run()
    lab_output = capsys.readouterr().out
    assert f"Chapter {int(number)} lab" in lab_output
    assert importlib.import_module(f"nosqlde.checks.{module}").run(solutions=True) == 0


@pytest.mark.parametrize(("number", "module", "connect"), CHAPTERS, ids=[c[0] for c in CHAPTERS])
def test_starter_exercises_fail_cleanly(
    number: str, module: str, connect: Callable[[], Any], capsys: pytest.CaptureFixture[str]
) -> None:
    _require(connect)
    assert importlib.import_module(f"nosqlde.checks.{module}").run(solutions=False) == 1
    out = capsys.readouterr().out
    assert "not implemented yet" in out and "Traceback" not in out


def test_capstone_end_to_end_then_chapter_7_check(capsys: pytest.CaptureFixture[str]) -> None:
    for connect in (clients.mongo, clients.redis_client, clients.cassandra, clients.neo4j):
        _require(connect)
    assert pipeline.main(scale=600) == 0
    out = capsys.readouterr().out
    assert "reconciliation: 6/6 OK" in out and "PASS" in out
    from nosqlde.checks import ch07_capstone

    assert ch07_capstone.run(solutions=True) == 0
