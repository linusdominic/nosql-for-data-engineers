"""Evaluate an answer: PASS or FAIL, with what was expected and what was got.

The rules every check follows:

* an empty answer (nothing but comments) fails before anything runs;
* the unchanged starter text fails;
* an answer whose statements raise an error fails with that error (unless a Verify
  check says errors are expected, as for a rejected conditional write);
* the reference solution's result must be non-empty; if it is not, that is a bug in the
  lesson and is reported as such, never as a pass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from nosqlde.studio.compare import Comparison, compare, records
from nosqlde.studio.lessons.model import Custom, Exercise, Match, Verify
from nosqlde.studio.runners import Consoles
from nosqlde.studio.runners.base import CHECK_ROWS, Block, RunResult, display


class LessonBug(RuntimeError):
    """The lesson's own reference or setup failed: not the learner's fault."""


@dataclass
class Outcome:
    ok: bool
    message: str
    expected: Any = None
    got: Any = None
    details: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "expected": display(self.expected),
            "got": display(self.got),
            "details": self.details,
        }


def passed(message: str, expected: Any = None, got: Any = None) -> Outcome:
    return Outcome(True, message, expected, got)


def failed(message: str, expected: Any = None, got: Any = None) -> Outcome:
    return Outcome(False, message, expected, got)


_COMMENT_LINE = {
    "mongo": re.compile(r"^\s*(//.*)?$"),
    "redis": re.compile(r"^\s*(#.*|//.*)?$"),
    "cql": re.compile(r"^\s*(--.*|//.*)?$"),
    "cypher": re.compile(r"^\s*(//.*)?$"),
    "dynamodb": re.compile(r"^\s*(--.*)?$"),
    "duckdb": re.compile(r"^\s*(--.*)?$"),
}


def meaningful(text: str, console: str) -> str:
    """The answer without comment-only lines and surrounding space."""
    pattern = _COMMENT_LINE.get(console, re.compile(r"^\s*$"))
    kept = [line for line in text.splitlines() if not pattern.match(line)]
    return "\n".join(kept).strip()


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class CheckRun:
    """What a check may do: run console text, in isolation from the console's session."""

    def __init__(self, consoles: Consoles, exercise: Exercise, answer: str = "") -> None:
        self.consoles = consoles
        self.exercise = exercise
        #: the answer being checked, for checks that run it again (idempotency)
        self.answer = answer

    def run(self, text: str, console: str | None = None) -> RunResult:
        return self.consoles.run(console or self.exercise.console, text, CHECK_ROWS, isolated=True)

    def setup(self, text: str, console: str | None = None, *, may_fail: bool = False) -> None:
        if not text.strip():
            return
        result = self.run(text, console)
        if result.error is not None and not may_fail:
            raise LessonBug(f"setup failed: {result.error.error_title}: {result.error.text}")

    def last(self, text: str, console: str | None = None) -> Block:
        result = self.run(text, console)
        if result.error is not None:
            raise LessonBug(f"check query failed: {result.error.error_title}: {result.error.text}")
        assert result.last is not None
        return result.last


def _error_outcome(result: RunResult) -> Outcome:
    err = result.error
    assert err is not None
    message = f"Your statement failed: {err.error_title}: {err.text}"
    if err.hint:
        message += f" ({err.hint})"
    return failed(message, got={"error": err.error_title, "message": err.text})


def _from_comparison(c: Comparison) -> Outcome:
    return Outcome(c.ok, c.message, c.expected, c.got)


def evaluate(consoles: Consoles, exercise: Exercise, answer: str) -> Outcome:
    body = meaningful(answer, exercise.console)
    if not body:
        return failed("Your answer is empty: write the statement in the console, then check it.")
    starter = meaningful(exercise.starter, exercise.console)
    if (
        starter
        and _squash(body) == _squash(starter)
        and _squash(starter) != _squash(meaningful(exercise.solution, exercise.console))
    ):
        return failed("This is still the starter text. Change it to answer the task, then check again.")
    run = CheckRun(consoles, exercise, answer)
    check = exercise.check
    if isinstance(check, Match):
        return _match(run, check, answer)
    if isinstance(check, Verify):
        return _verify(run, check, answer)
    if isinstance(check, Custom):
        run.setup(check.setup)
        result = run.run(answer)
        if result.error is not None:
            return _error_outcome(result)
        return check.fn(run, result)
    raise LessonBug(f"unknown check type {type(check).__name__}")  # pragma: no cover


def _match(run: CheckRun, check: Match, answer: str) -> Outcome:
    run.setup(check.setup)
    reference = run.run(run.exercise.solution)
    if reference.error is not None or reference.last is None:
        err = reference.error
        raise LessonBug(
            f"the reference solution failed: {err.error_title if err else ''} {err.text if err else ''}"
        )
    expected = records(reference.last)
    if not expected or expected == [{"value": None}]:
        raise LessonBug("the reference solution returned nothing")
    run.setup(check.setup)
    result = run.run(answer)
    if result.error is not None:
        return _error_outcome(result)
    assert result.last is not None
    got = records(result.last)
    if got == [{"value": None}]:
        got = []
    return _from_comparison(
        compare(
            expected,
            got,
            fields=check.fields,
            ordered=check.ordered,
            by_position=check.by_position,
            extra_ok=check.extra_ok,
        )
    )


def _apply(
    run: CheckRun, check: Verify, text: str, *, is_reference: bool
) -> tuple[RunResult | None, list[dict[str, Any]]]:
    """setup, then the statements `runs` times (verifying after each run if asked).
    Returns (the first failing result, if errors are not allowed; the verified records)."""
    run.setup(check.setup)
    seen: list[dict[str, Any]] = []
    for i in range(check.runs):
        if i and check.between.strip():
            run.setup(check.between, may_fail=check.between_may_fail)
        result = run.run(text)
        if result.error is not None and not check.allow_errors:
            if is_reference:
                raise LessonBug(
                    f"the reference solution failed: {result.error.error_title}: {result.error.text}"
                )
            return result, []
        if check.verify_each_run or i == check.runs - 1:
            rows = records(run.last(check.verify))
            if rows == [{"value": None}]:
                rows = []
            if check.verify_each_run:
                rows = [{"after_run": i + 1, **r} for r in rows] or [
                    {"after_run": i + 1, "state": "(nothing)"}
                ]
            seen.extend(rows)
    return None, seen


def _verify(run: CheckRun, check: Verify, answer: str) -> Outcome:
    _, expected = _apply(run, check, run.exercise.solution, is_reference=True)
    if not expected or all(r.get("state") == "(nothing)" for r in expected):
        raise LessonBug("the verification query returned nothing after the reference solution")
    bad, got = _apply(run, check, answer, is_reference=False)
    if bad is not None:
        return _error_outcome(bad)
    fields = check.fields
    if fields and check.verify_each_run:
        fields = ("after_run", *fields)
    c = compare(
        expected,
        got,
        fields=fields,
        ordered=check.ordered or check.verify_each_run,
        by_position=check.by_position,
    )
    if c.ok:
        c.message = "The data is in the expected state afterwards: " + c.message[0].lower() + c.message[1:]
    else:
        c.message = (
            f"After your statements, `{_squash(check.verify)[:100]}` does not return what it should. "
            + c.message
        )
    return _from_comparison(c)
