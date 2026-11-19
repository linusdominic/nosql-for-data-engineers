"""The lesson studio against the live databases.

For every exercise: the reference solution passes its check, every listed plausible wrong
answer fails, and a statement that does nothing fails. Then one test drives the HTTP API
with the token: prepare, run, check (wrong, then right), solution, a streamed job.

Needs the same containers as the other integration tests (make up-capstone up-05). A
lesson whose database is unreachable is skipped, unless NOSQLDE_REQUIRE_SERVICES is set.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nosqlde import clients
from nosqlde.config import SETTINGS
from nosqlde.studio.checking import evaluate
from nosqlde.studio.lessons.model import Exercise
from nosqlde.studio.progress import Progress
from nosqlde.studio.registry import LESSONS
from nosqlde.studio.runners import Consoles
from nosqlde.studio.server import create_app

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.integration

#: a statement per console that runs fine and changes nothing
NOOP = {
    "mongo": "db.getCollectionNames()",
    "redis": "PING",
    "cql": "SELECT release_version FROM system.local;",
    "cypher": "RETURN 1 AS one",
    "dynamodb": "SELECT * FROM larkspur_studio WHERE PK = 'NOPE'",
    "duckdb": "SELECT 1 AS one",
}
NEEDS: dict[str, list[Callable[[], Any]]] = {
    "ch02": [clients.mongo],
    "ch03": [clients.redis_client],
    "ch04": [clients.cassandra],
    "ch05": [clients.dynamodb_client],
    "ch06": [clients.neo4j],
    "ch07": [],
}


def _require(connect: Callable[[], Any]) -> None:
    try:
        conn = connect()
    except clients.ServiceUnavailable as err:
        if os.environ.get("NOSQLDE_REQUIRE_SERVICES"):
            raise
        pytest.skip(str(err).splitlines()[0])
    if hasattr(type(conn), "close"):
        conn.close()
    elif hasattr(type(conn), "shutdown"):
        conn.cluster.shutdown()


@pytest.fixture(autouse=True)
def _root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOSQLDE_ROOT", str(ROOT))
    monkeypatch.chdir(ROOT)


@pytest.fixture(scope="module")
def consoles() -> Iterator[Consoles]:
    c = Consoles()
    yield c
    c.close()


_prepared: set[str] = set()


def _prepare(lesson_id: str) -> None:
    """Prepare each lesson once per session, right before its first exercise."""
    for connect in NEEDS[lesson_id]:
        _require(connect)
    if lesson_id in _prepared:
        return
    os.chdir(ROOT)
    lesson = LESSONS[lesson_id]
    if lesson.prepare is not None:
        lesson.prepare()
    elif lesson_id == "ch07" and not (SETTINGS.lake_dir / "capstone" / "marts" / "fct_loan.parquet").exists():
        for connect in (clients.mongo, clients.redis_client, clients.cassandra, clients.neo4j):
            _require(connect)
        from nosqlde.capstone import pipeline

        assert pipeline.main(scale=600) == 0
    _prepared.add(lesson_id)


CASES = [(lesson.id, x) for lesson in LESSONS.values() for x in lesson.exercises]


@pytest.mark.parametrize(("lesson_id", "exercise"), CASES, ids=[x.id for _, x in CASES])
def test_solution_passes_and_wrong_answers_fail(
    lesson_id: str, exercise: Exercise, consoles: Consoles
) -> None:
    _prepare(lesson_id)
    outcome = evaluate(consoles, exercise, exercise.solution)
    assert outcome.ok, (
        f"reference solution failed: {outcome.message}\nexpected {outcome.expected}\ngot {outcome.got}"
    )
    for wrong in (*exercise.wrong, NOOP[exercise.console], ""):
        bad = evaluate(consoles, exercise, wrong)
        assert not bad.ok, f"this wrong answer passed:\n{wrong}"
    # the reference passes again after the wrong answers (checks restore their own state)
    assert evaluate(consoles, exercise, exercise.solution).ok


def test_http_api_with_token(tmp_path: Path) -> None:
    _require(clients.redis_client)
    token = "integration-token"
    app = create_app(token, 8790, progress=Progress(tmp_path / "progress.json"))
    h = {"X-Studio-Token": token}
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        assert client.post("/api/run", json={"console": "redis", "text": "PING"}).status_code == 401

        prep = client.post("/api/prepare/ch03", headers=h)
        assert prep.status_code == 200, prep.text
        assert any("21 entries" in line for line in prep.json()["lines"])

        run = client.post(
            "/api/run", json={"console": "redis", "text": "ZREVRANGE ch03:scores 0 2 WITHSCORES"}, headers=h
        )
        assert run.status_code == 200
        assert run.json()["blocks"][0]["text"].startswith('1) "A0000004"\n2) "826"')

        status = client.get("/api/status", headers=h).json()["services"]
        assert next(s for s in status if s["id"] == "redis")["up"] is True

        assert client.post("/api/solution", json={"exercise_id": "ch03.top3"}, headers=h).status_code == 403
        wrong = client.post(
            "/api/check",
            json={"exercise_id": "ch03.top3", "answer": "ZRANGE ch03:scores 0 2 WITHSCORES"},
            headers=h,
        ).json()
        assert wrong["ok"] is False and wrong["expected"] and wrong["got"]
        solution = client.post("/api/solution", json={"exercise_id": "ch03.top3"}, headers=h).json()[
            "solution"
        ]
        right = client.post(
            "/api/check", json={"exercise_id": "ch03.top3", "answer": solution}, headers=h
        ).json()
        assert (
            right["ok"] is True and right["progress"]["attempts"] == 2 and right["progress"]["passed"] is True
        )
        assert right["lesson"]["done"] == 1

        refused = client.post("/api/run", json={"console": "redis", "text": "FLUSHALL"}, headers=h).json()
        assert refused["blocks"][0]["kind"] == "error" and "FLUSHDB" in refused["blocks"][0]["text"]

        _require(clients.mongo)
        with client.stream("POST", "/api/jobs/lab-02", headers=h) as res:
            assert res.status_code == 200
            text = "".join(res.iter_text())
        assert "Chapter 2 lab" in text and "[exit code 0" in text
