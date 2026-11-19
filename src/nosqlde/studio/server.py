"""The lesson studio's HTTP server: FastAPI on 127.0.0.1, guarded by nosqlde.studio.security.

The browser gets lessons (without solutions), sends console text to /api/run, answers to
/api/check, and streams fixed jobs (the capstone, a chapter's lab) from /api/jobs/<id>.
Nothing the browser sends is ever passed to a shell: console text goes to a database
driver, and a job id selects one of a fixed list of `nosqlde` commands.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nosqlde import __version__
from nosqlde.clients import ServiceUnavailable
from nosqlde.studio import checking
from nosqlde.studio.lessons.model import REPO, Job
from nosqlde.studio.paths import progress_file, repo_root
from nosqlde.studio.progress import Progress
from nosqlde.studio.registry import LESSONS, find_exercise
from nosqlde.studio.runners import CONSOLES, Consoles
from nosqlde.studio.runners.base import DISPLAY_ROWS
from nosqlde.studio.security import Guard

STATIC = Path(__file__).parent / "static"
DEFAULT_PORT = 8790
EXPLORER = "https://linusdominic.github.io/nosql-for-data-engineers/explorer/"
MAX_TEXT = 100_000

LAB_JOBS = {
    f"lab-{n:02d}": Job(
        id=f"lab-{n:02d}", label=f"Run the whole lab (make lab-{n:02d})", argv=("lab", f"{n:02d}")
    )
    for n in range(2, 7)
}


class RunRequest(BaseModel):
    console: str = Field(max_length=20)
    text: str = Field(max_length=MAX_TEXT)


class CheckRequest(BaseModel):
    exercise_id: str = Field(max_length=80)
    answer: str = Field(max_length=MAX_TEXT)


class SolutionRequest(BaseModel):
    exercise_id: str = Field(max_length=80)


class QuizRequest(BaseModel):
    answers: dict[str, str] = Field(max_length=50)


class ResetRequest(BaseModel):
    lesson_id: str | None = Field(default=None, max_length=20)


def all_jobs() -> dict[str, Job]:
    jobs = dict(LAB_JOBS)
    for lesson in LESSONS.values():
        for job in lesson.jobs:
            jobs[job.id] = job
    return jobs


def lesson_progress(lesson_id: str, progress: Progress) -> dict[str, Any]:
    lesson = LESSONS[lesson_id]
    snap = progress.snapshot()
    exercises = {
        x.id: {k: v for k, v in snap["exercises"].get(x.id, {}).items() if k != "last_answer"}
        for x in lesson.exercises
    }
    drafts = {x.id: snap["exercises"].get(x.id, {}).get("last_answer") for x in lesson.exercises}
    quiz = snap["quizzes"].get(lesson_id, {})
    done = sum(1 for x in lesson.exercises if exercises[x.id].get("passed")) + sum(
        1 for q in lesson.quiz if quiz.get(q.id, {}).get("correct")
    )
    total = len(lesson.exercises) + len(lesson.quiz)
    return {
        "exercises": exercises,
        "drafts": drafts,
        "quiz": quiz,
        "done": done,
        "total": total,
        "prepared": snap["prepared"].get(lesson_id),
    }


def create_app(
    token: str, port: int, *, consoles: Consoles | None = None, progress: Progress | None = None
) -> Any:
    """The ASGI app: FastAPI wrapped in the Guard middleware."""
    app = FastAPI(title="NoSQL lesson studio", docs_url=None, redoc_url=None, openapi_url=None)
    cons = consoles or Consoles()
    prog = progress or Progress(progress_file())
    job_lock = threading.Lock()
    prepare_locks = {lid: threading.Lock() for lid in LESSONS}
    app.state.consoles = cons
    app.state.progress = prog

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", media_type="text/html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        return {
            "version": __version__,
            "repo": REPO,
            "explorer": EXPLORER,
            "consoles": [vars(c) for c in CONSOLES.values()],
            "lessons": [
                {
                    **lesson.summary_json(),
                    "progress": {
                        k: v for k, v in lesson_progress(lesson.id, prog).items() if k in ("done", "total")
                    },
                }
                for lesson in LESSONS.values()
            ],
            "display_rows": DISPLAY_ROWS,
        }

    @app.get("/api/lessons/{lesson_id}")
    def lesson(lesson_id: str) -> dict[str, Any]:
        found = LESSONS.get(lesson_id)
        if found is None:
            raise HTTPException(404, f"no lesson {lesson_id!r}")
        return {**found.public(), "progress": lesson_progress(lesson_id, prog)}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return {"services": cons.status()}

    @app.post("/api/run")
    def run(req: RunRequest) -> dict[str, Any]:
        if req.console not in CONSOLES:
            raise HTTPException(400, f"unknown console {req.console!r}")
        return cons.run(req.console, req.text).to_json()

    @app.post("/api/check")
    def check(req: CheckRequest) -> dict[str, Any]:
        found = find_exercise(req.exercise_id)
        if found is None:
            raise HTTPException(404, f"no exercise {req.exercise_id!r}")
        lesson_obj, exercise = found
        try:
            outcome = checking.evaluate(cons, exercise, req.answer)
        except checking.LessonBug as err:
            raise HTTPException(
                409,
                f"The check could not set up or run its reference ({err}). The chapter's data is probably "
                "missing or was changed by a lab or another lesson: press Prepare data, then check again.",
            ) from err
        except ServiceUnavailable as err:
            raise HTTPException(503, str(err).splitlines()[0]) from err
        entry = prog.record_attempt(exercise.id, req.answer, outcome.ok)
        body = outcome.to_json()
        body["progress"] = {k: v for k, v in entry.items() if k != "last_answer"}
        body["lesson"] = {
            k: v for k, v in lesson_progress(lesson_obj.id, prog).items() if k in ("done", "total")
        }
        if outcome.ok and exercise.explain:
            body["explain"] = exercise.explain
        return body

    @app.post("/api/solution")
    def solution(req: SolutionRequest) -> dict[str, Any]:
        found = find_exercise(req.exercise_id)
        if found is None:
            raise HTTPException(404, f"no exercise {req.exercise_id!r}")
        _, exercise = found
        if int(prog.exercise(exercise.id).get("attempts", 0)) < 1:
            raise HTTPException(
                403, "Check an answer of your own first; the solution opens after one attempt."
            )
        prog.record_reveal(exercise.id)
        return {"solution": exercise.solution, "explain": exercise.explain}

    @app.post("/api/quiz/{lesson_id}")
    def quiz(lesson_id: str, req: QuizRequest) -> dict[str, Any]:
        found = LESSONS.get(lesson_id)
        if found is None or not found.quiz:
            raise HTTPException(404, f"no quiz for {lesson_id!r}")
        results: dict[str, Any] = {}
        correct: dict[str, bool] = {}
        given: dict[str, str] = {}
        for q in found.quiz:
            letter = str(req.answers.get(q.id, "")).strip().lower()[:1]
            if not letter:
                results[q.id] = {"answered": False}
                continue
            ok = letter == q.answer
            correct[q.id] = ok
            given[q.id] = letter
            results[q.id] = {
                "answered": True,
                "ok": ok,
                "why": q.why if ok else f"You answered {letter}. {q.why}",
            }
        prog.record_quiz(lesson_id, given, correct)
        return {"results": results, "progress": lesson_progress(lesson_id, prog)}

    @app.post("/api/prepare/{lesson_id}")
    def prepare(lesson_id: str) -> dict[str, Any]:
        found = LESSONS.get(lesson_id)
        if found is None or found.prepare is None:
            raise HTTPException(404, f"no prepare step for {lesson_id!r}")
        lock = prepare_locks[lesson_id]
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "Prepare is already running for this lesson.")
        try:
            result = found.prepare()
        except ServiceUnavailable as err:
            raise HTTPException(503, " ".join(str(err).split())) from err
        finally:
            lock.release()
        prog.record_prepared(lesson_id, result.seconds)
        return {"lines": result.lines, "seconds": result.seconds}

    @app.post("/api/progress/reset")
    def reset(req: ResetRequest) -> dict[str, Any]:
        if req.lesson_id is not None and req.lesson_id not in LESSONS:
            raise HTTPException(404, f"no lesson {req.lesson_id!r}")
        prog.reset(req.lesson_id)
        return {"ok": True}

    @app.post("/api/jobs/{job_id}")
    def job(job_id: str) -> StreamingResponse:
        jobs = all_jobs()
        if job_id not in jobs:
            raise HTTPException(404, f"no job {job_id!r}")
        if not job_lock.acquire(blocking=False):
            raise HTTPException(409, "Another job is running; wait for it to finish.")
        return StreamingResponse(_stream(jobs[job_id], job_lock), media_type="text/plain; charset=utf-8")

    guarded = Guard(app, token=token, port=port)
    guarded.fastapi = app  # type: ignore[attr-defined]
    return guarded


def _stream(job: Job, lock: threading.Lock) -> Iterator[str]:
    """Run `python -m nosqlde.cli <argv>` (a fixed command, never browser input) and
    yield its output line by line, then a last line with the exit code."""
    start = time.perf_counter()
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    try:
        proc = subprocess.Popen(  # a fixed argv from the Job table, never browser input
            [sys.executable, "-m", "nosqlde.cli", *job.argv],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=repo_root(),
            env=env,
            text=True,
            bufsize=1,
        )
    except OSError as err:
        lock.release()
        yield f"could not start the job: {err}\n"
        return
    try:
        yield f"$ nosqlde {' '.join(job.argv)}\n"
        assert proc.stdout is not None
        yield from proc.stdout
        code = proc.wait()
        yield f"\n[exit code {code} after {time.perf_counter() - start:.1f}s]\n"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        lock.release()


def new_token() -> str:
    return secrets.token_urlsafe(24)


def serve(port: int = DEFAULT_PORT) -> int:
    """Start the studio on 127.0.0.1:<port> and print the URL with its token."""
    import socket

    import uvicorn

    root = repo_root()
    if not (root / "guide").is_dir() or not (root / "exercises").is_dir():
        print(
            f"Run the studio from the repository root (no guide/ or exercises/ in {root}).", file=sys.stderr
        )
        return 2
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            print(
                f"Port {port} is in use. Start the studio on another one: make studio STUDIO_PORT=8791",
                file=sys.stderr,
            )
            return 2
    token = new_token()
    app = create_app(token, port)
    url = f"http://127.0.0.1:{port}/?token={token}"
    print("NoSQL lesson studio")
    print(f"  open {url}")
    print("  (the token changes every start; the server listens on 127.0.0.1 only. Ctrl+C stops it.)")
    sys.stdout.flush()
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", access_log=False, server_header=False
    )
    server = uvicorn.Server(config)
    try:
        server.run()
    finally:
        app.fastapi.state.consoles.close()
    return 0
