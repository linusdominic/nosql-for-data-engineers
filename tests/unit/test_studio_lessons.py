"""Lesson integrity: every exercise is complete and checkable, ids are unique, consoles
exist, guide links point at real headings, and the quizzes match the existing checks."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from nosqlde.checks import ch01_foundations, ch08_choosing
from nosqlde.studio.checking import meaningful
from nosqlde.studio.lessons.model import GUIDE_FILES, REPO, Custom, GuideRef, Match, Verify, slug
from nosqlde.studio.registry import LESSONS, find_exercise
from nosqlde.studio.runners import CONSOLES
from nosqlde.studio.server import all_jobs

ROOT = Path(__file__).resolve().parents[2]
EXERCISES = [x for lesson in LESSONS.values() for x in lesson.exercises]


def headings(chapter: int) -> set[str]:
    text = (ROOT / "guide" / GUIDE_FILES[chapter]).read_text()
    return {slug(m.group(1)) for m in re.finditer(r"^#+ (.+)$", text, flags=re.MULTILINE)}


def all_guide_refs() -> list[GuideRef]:
    refs = []
    for lesson in LESSONS.values():
        refs.append(lesson.guide)
        refs.extend(step.guide for step in lesson.steps)
    return refs


def test_lessons_cover_chapters_1_to_8_in_order() -> None:
    assert list(LESSONS) == [f"ch0{n}" for n in range(1, 9)]
    assert [lesson.number for lesson in LESSONS.values()] == list(range(1, 9))


@pytest.mark.parametrize("lesson_id", ["ch02", "ch03", "ch04", "ch05", "ch06"])
def test_database_chapters_have_6_to_10_exercises(lesson_id: str) -> None:
    lesson = LESSONS[lesson_id]
    assert 6 <= len(lesson.exercises) <= 10
    assert lesson.prepare is not None and lesson.make_up == f"make up-{lesson_id[2:]}"


def test_capstone_lesson_runs_the_capstone_and_has_duckdb_exercises() -> None:
    lesson = LESSONS["ch07"]
    assert [j.argv for j in lesson.jobs] == [("capstone",)]
    assert lesson.exercises and all(x.console == "duckdb" for x in lesson.exercises)


def test_ids_are_unique() -> None:
    ids = [x.id for x in EXERCISES]
    assert len(ids) == len(set(ids))
    for lesson in LESSONS.values():
        assert all(x.id.startswith(lesson.id + ".") for x in lesson.exercises)
        numbers = [x.number for x in lesson.exercises]
        assert len(numbers) == len(set(numbers))
        step_ids = [s.id for s in lesson.steps]
        assert len(step_ids) == len(set(step_ids))
    assert find_exercise(EXERCISES[0].id) is not None and find_exercise("nope") is None


@pytest.mark.parametrize("exercise", EXERCISES, ids=lambda x: x.id)
def test_every_exercise_is_complete(exercise) -> None:  # type: ignore[no-untyped-def]
    assert exercise.console in CONSOLES
    assert exercise.task.strip() and exercise.title.strip()
    assert meaningful(exercise.solution, exercise.console), "no solution"
    assert 1 <= len(exercise.hints) <= 3 and all(h.strip() for h in exercise.hints)
    assert isinstance(exercise.check, (Match, Verify, Custom))
    assert exercise.wrong, (
        "every exercise needs at least one plausible wrong answer for the integration tests"
    )
    assert exercise.solution not in exercise.wrong
    assert re.sub(r"\s+", " ", exercise.starter) != re.sub(r"\s+", " ", exercise.solution), (
        "the starter must not be the answer"
    )


def test_examples_use_known_consoles() -> None:
    for lesson in LESSONS.values():
        for step in lesson.steps:
            for ex in step.examples:
                assert ex.console in CONSOLES and ex.code.strip() and ex.title.strip()
            assert step.prose, step.id


@pytest.mark.parametrize("ref", all_guide_refs(), ids=lambda r: f"{r.chapter}:{r.heading}")
def test_guide_links_point_at_real_headings(ref: GuideRef) -> None:
    assert slug(ref.heading) in headings(ref.chapter), f"no heading {ref.heading!r} in {ref.file}"
    assert ref.url.startswith(f"{REPO}/blob/main/guide/{ref.file}#")


def test_slug_matches_github() -> None:
    assert slug("Indexes and `explain()`") == "indexes-and-explain"
    assert slug("Embed or reference?") == "embed-or-reference"
    assert slug("`PROFILE`: index seek versus label scan") == "profile-index-seek-versus-label-scan"


@pytest.mark.parametrize(("lesson_id", "key"), [("ch01", ch01_foundations.KEY), ("ch08", ch08_choosing.KEY)])
def test_quizzes_reuse_the_exercise_files_and_answer_keys(
    lesson_id: str, key: dict[str, tuple[str, str]]
) -> None:
    quiz = LESSONS[lesson_id].quiz
    assert [q.id for q in quiz] == list(key)
    for q in quiz:
        letters = [letter for letter, _ in q.options]
        assert letters == ["a", "b", "c", "d"], q.id
        assert all(text for _, text in q.options)
        assert (q.answer, q.why) == key[q.id]
        assert q.question and not re.search(r"\b[a-d]\)", q.question)


def test_jobs_are_a_fixed_list_of_nosqlde_commands() -> None:
    jobs = all_jobs()
    assert set(jobs) == {"capstone", "lab-02", "lab-03", "lab-04", "lab-05", "lab-06"}
    assert all(j.argv[0] in ("capstone", "lab") for j in jobs.values())
