"""The shape of a lesson: steps with prose, runnable examples and checked exercises.

Lessons are data. Each chapter module builds one `Lesson` from these dataclasses; the
server sends them to the browser (without solutions or check internals) and the check
engine in nosqlde.studio.checking evaluates answers against them.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nosqlde.studio.checking import CheckRun, Outcome
    from nosqlde.studio.runners.base import RunResult

REPO = "https://github.com/linusdominic/nosql-for-data-engineers"

GUIDE_FILES = {
    0: "00-setup.md",
    1: "01-why-nosql.md",
    2: "02-document-stores-mongodb.md",
    3: "03-key-value-redis.md",
    4: "04-wide-column-cassandra.md",
    5: "05-dynamodb.md",
    6: "06-graph-neo4j.md",
    7: "07-capstone.md",
    8: "08-choosing-a-nosql-database.md",
}


def slug(heading: str) -> str:
    """GitHub's heading anchor: lower case, punctuation dropped, spaces to hyphens."""
    s = heading.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


@dataclass(frozen=True)
class GuideRef:
    """A heading in a guide chapter. Tests check that the heading exists."""

    chapter: int
    heading: str

    @property
    def file(self) -> str:
        return GUIDE_FILES[self.chapter]

    @property
    def url(self) -> str:
        return f"{REPO}/blob/main/guide/{self.file}#{slug(self.heading)}"


@dataclass(frozen=True)
class Example:
    """A "run this" snippet: one click loads it into the console and runs it."""

    title: str
    console: str
    code: str
    note: str = ""


# ---------------------------------------------------------------- checks


@dataclass(frozen=True)
class Match:
    """Run the reference solution and the answer; compare the last result of each.

    fields: compare only these columns/fields (default: every field the reference returns)
    ordered: the task asks for an order
    by_position: compare values column by column, ignoring column names (counts)
    extra_ok: the answer may return more fields than the reference
    setup: console text run before each of the two runs (restores the starting state)
    """

    fields: tuple[str, ...] | None = None
    ordered: bool = False
    by_position: bool = False
    extra_ok: bool = True
    setup: str = ""


@dataclass(frozen=True)
class Verify:
    """For writes and DDL: run setup, the statements, then `verify`; compare what
    `verify` returns after the reference solution with what it returns after the answer.

    runs: run the statements this many times (2 checks idempotency)
    between: console text run before each run after the first (for example, a competing
        writer that changes the row), so a conditional write must hold back
    between_may_fail: `between` may raise (it is itself a conditional write)
    allow_errors: an error in the answer's runs is fine (a rejected conditional write)
    verify_each_run: run `verify` after every run and compare the whole sequence
    """

    verify: str
    setup: str = ""
    runs: int = 1
    between: str = ""
    between_may_fail: bool = False
    allow_errors: bool = False
    verify_each_run: bool = False
    fields: tuple[str, ...] | None = None
    ordered: bool = False
    by_position: bool = False


@dataclass(frozen=True)
class Custom:
    """A Python check: fn(run, answer_result) -> Outcome. `setup` runs before the answer."""

    fn: Callable[[CheckRun, RunResult], Outcome]
    setup: str = ""
    description: str = ""


Check = Match | Verify | Custom


@dataclass(frozen=True)
class Exercise:
    id: str  # unique, e.g. "ch02.lookup"
    number: str  # as shown, e.g. "2.1"
    title: str
    console: str
    task: str
    starter: str
    hints: tuple[str, ...]
    solution: str
    check: Check
    #: plausible wrong answers; integration tests make sure each one fails
    wrong: tuple[str, ...]
    explain: str = ""  # shown after a pass: why it works

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "number": self.number,
            "title": self.title,
            "console": self.console,
            "task": self.task,
            "starter": self.starter,
            "hints": list(self.hints),
            "kind": type(self.check).__name__.lower(),
        }


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    prose: tuple[str, ...]
    guide: GuideRef
    examples: tuple[Example, ...] = ()
    exercises: tuple[Exercise, ...] = ()

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "prose": list(self.prose),
            "guide": {"url": self.guide.url, "heading": self.guide.heading, "file": self.guide.file},
            "examples": [
                {"title": e.title, "console": e.console, "code": e.code, "note": e.note}
                for e in self.examples
            ],
            "exercises": [x.public() for x in self.exercises],
        }


@dataclass(frozen=True)
class QuizQuestion:
    id: str
    question: str
    options: tuple[tuple[str, str], ...]  # (letter, text)
    answer: str
    why: str


@dataclass(frozen=True)
class Job:
    """A fixed command the studio may run and stream (never anything the browser sends)."""

    id: str
    label: str
    argv: tuple[str, ...]  # arguments to `nosqlde`
    stages: tuple[tuple[str, str], ...] = ()  # (marker in the output, label)


@dataclass
class PrepareResult:
    lines: list[str] = field(default_factory=list)
    seconds: float = 0.0


@dataclass(frozen=True)
class Lesson:
    id: str  # "ch02"
    number: int
    title: str
    database: str
    summary: str
    guide: GuideRef
    consoles: tuple[str, ...] = ()
    services: tuple[str, ...] = ()  # status ids this lesson needs
    make_up: str = ""
    steps: tuple[Step, ...] = ()
    prepare: Callable[[], PrepareResult] | None = None
    prepare_note: str = ""
    quiz: tuple[QuizQuestion, ...] = ()
    jobs: tuple[Job, ...] = ()

    @property
    def exercises(self) -> list[Exercise]:
        return [x for s in self.steps for x in s.exercises]

    def exercise(self, exercise_id: str) -> Exercise | None:
        return next((x for x in self.exercises if x.id == exercise_id), None)

    def summary_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "number": self.number,
            "title": self.title,
            "database": self.database,
            "summary": self.summary,
            "exercise_ids": [x.id for x in self.exercises],
            "quiz_ids": [q.id for q in self.quiz],
            "make_up": self.make_up,
        }

    def public(self) -> dict[str, Any]:
        return {
            **self.summary_json(),
            "guide": {"url": self.guide.url, "file": self.guide.file},
            "consoles": list(self.consoles),
            "services": list(self.services),
            "has_prepare": self.prepare is not None,
            "prepare_note": self.prepare_note,
            "steps": [s.public() for s in self.steps],
            "quiz": [
                {"id": q.id, "question": q.question, "options": [list(o) for o in q.options]}
                for q in self.quiz
            ],
            "jobs": [
                {"id": j.id, "label": j.label, "stages": [list(s) for s in j.stages]} for j in self.jobs
            ],
        }
