"""The studio's request protection: token, Host (DNS rebinding), Origin, headers. No database:
the consoles connect lazily, and no test here runs a console."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nosqlde.studio.progress import Progress
from nosqlde.studio.security import MAX_BODY_BYTES, SECURITY_HEADERS, token_ok, verdict
from nosqlde.studio.server import create_app, new_token

PORT = 8790
TOKEN = "t0ken-for-tests"
OK_HEADERS = {"host": f"127.0.0.1:{PORT}", "x-studio-token": TOKEN}


def v(method: str = "GET", path: str = "/api/meta", **headers: str) -> tuple[int, str] | None:
    h = {**OK_HEADERS, **{k.replace("_", "-"): val for k, val in headers.items()}}
    h = {k: val for k, val in h.items() if val != ""}
    return verdict(method=method, path=path, headers=h, token=TOKEN, port=PORT)


def test_good_request_passes() -> None:
    assert v() is None
    assert v(host=f"localhost:{PORT}") is None
    assert v(origin=f"http://127.0.0.1:{PORT}") is None
    assert v(sec_fetch_site="same-origin") is None


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        f"evil.example:{PORT}",
        "127.0.0.1",
        f"127.0.0.1:{PORT + 1}",
        f"0.0.0.0:{PORT}",
        f"[::1]:{PORT}",
        "",
    ],
)
def test_foreign_or_missing_host_is_refused(host: str) -> None:
    result = v(host=host)
    assert result is not None and result[0] == 421


@pytest.mark.parametrize(
    "origin", ["http://evil.example", f"http://127.0.0.1:{PORT + 1}", f"https://127.0.0.1:{PORT}", "null"]
)
def test_foreign_origin_is_refused(origin: str) -> None:
    result = v(origin=origin)
    assert result is not None and result[0] == 403


def test_api_needs_the_token_but_static_files_do_not() -> None:
    result = v(x_studio_token="")
    assert result is not None and result[0] == 401
    result = v(x_studio_token="wrong")
    assert result is not None and result[0] == 401
    assert v(path="/", x_studio_token="") is None
    assert v(path="/static/app.js", x_studio_token="") is None
    assert v(path="/api", x_studio_token="")[0] == 401  # type: ignore[index]


def test_cross_site_and_preflight_are_refused() -> None:
    assert v(sec_fetch_site="cross-site")[0] == 403  # type: ignore[index]
    assert v(method="OPTIONS")[0] == 403  # type: ignore[index]


def test_body_size_limit() -> None:
    assert v(method="POST", content_length=str(MAX_BODY_BYTES + 1))[0] == 413  # type: ignore[index]
    assert v(method="POST", content_length="abc")[0] == 400  # type: ignore[index]


def test_token_comparison_and_generation() -> None:
    assert token_ok(TOKEN, TOKEN) and not token_ok(None, TOKEN) and not token_ok(TOKEN + "x", TOKEN)
    a, b = new_token(), new_token()
    assert a != b and len(a) >= 32


# ---------------------------------------------------------------- through HTTP


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(TOKEN, PORT, progress=Progress(tmp_path / "progress.json"))
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}")


def test_http_token_host_origin(client: TestClient) -> None:
    assert client.get("/api/meta").status_code == 401
    assert client.get("/api/meta", headers={"X-Studio-Token": "nope"}).status_code == 401
    assert (
        client.get("/api/meta", headers={"X-Studio-Token": TOKEN, "Host": "evil.example"}).status_code == 421
    )
    assert (
        client.get(
            "/api/meta", headers={"X-Studio-Token": TOKEN, "Origin": "http://evil.example"}
        ).status_code
        == 403
    )
    assert (
        client.options(
            "/api/run", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"}
        ).status_code
        == 403
    )
    ok = client.get("/api/meta", headers={"X-Studio-Token": TOKEN})
    assert ok.status_code == 200
    assert {lesson["id"] for lesson in ok.json()["lessons"]} == {f"ch0{n}" for n in range(1, 9)}
    assert "access-control-allow-origin" not in ok.headers


def test_http_security_headers_on_every_response(client: TestClient) -> None:
    for res in (client.get("/"), client.get("/static/app.js"), client.get("/api/meta")):
        for name, value in SECURITY_HEADERS.items():
            assert res.headers.get(name) == value, (res.url, name)
    assert "'unsafe-inline'" not in SECURITY_HEADERS["content-security-policy"]


def test_http_index_has_no_inline_script(client: TestClient) -> None:
    html = client.get("/").text
    assert "<script>" not in html and 'src="/static/app.js"' in html


def test_http_validation_and_unknown_things(client: TestClient) -> None:
    h = {"X-Studio-Token": TOKEN}
    assert client.post("/api/run", json={"console": "bash", "text": "ls"}, headers=h).status_code == 400
    assert (
        client.post("/api/run", json={"console": "redis", "text": "x" * 100_001}, headers=h).status_code
        == 422
    )
    assert client.post("/api/jobs/rm-rf", headers=h).status_code == 404
    assert client.post("/api/prepare/ch01", headers=h).status_code == 404
    assert (
        client.post("/api/check", json={"exercise_id": "nope", "answer": "x"}, headers=h).status_code == 404
    )
    assert client.get("/api/lessons/ch99", headers=h).status_code == 404


def test_http_solution_opens_only_after_an_attempt(client: TestClient) -> None:
    h = {"X-Studio-Token": TOKEN}
    res = client.post("/api/solution", json={"exercise_id": "ch02.lookup"}, headers=h)
    assert res.status_code == 403
    # an empty answer is checked without touching a database, and counts as an attempt
    check = client.post(
        "/api/check", json={"exercise_id": "ch02.lookup", "answer": "// nothing yet"}, headers=h
    )
    assert check.status_code == 200 and check.json()["ok"] is False and "empty" in check.json()["message"]
    res = client.post("/api/solution", json={"exercise_id": "ch02.lookup"}, headers=h)
    assert res.status_code == 200 and "$lookup" in res.json()["solution"]


def test_http_lessons_never_send_solutions(client: TestClient) -> None:
    h = {"X-Studio-Token": TOKEN}
    for lid in ("ch02", "ch03", "ch04", "ch05", "ch06", "ch07"):
        body = client.get(f"/api/lessons/{lid}", headers=h).json()
        for step in body["steps"]:
            for ex in step["exercises"]:
                assert "solution" not in ex and "wrong" not in ex


def test_http_quiz_and_progress(client: TestClient, tmp_path: Path) -> None:
    h = {"X-Studio-Token": TOKEN}
    res = client.post("/api/quiz/ch01", json={"answers": {"1.1": "b", "1.2": "a"}}, headers=h).json()
    assert res["results"]["1.1"]["ok"] is True
    assert res["results"]["1.2"]["ok"] is False and res["results"]["1.2"]["why"].startswith("You answered a.")
    assert res["results"]["1.3"] == {"answered": False}
    assert res["progress"]["done"] == 1
    assert (tmp_path / "progress.json").exists()
    assert client.post("/api/progress/reset", json={"lesson_id": "ch01"}, headers=h).json() == {"ok": True}
    assert client.get("/api/lessons/ch01", headers=h).json()["progress"]["done"] == 0
