"""Every lesson, by id, in chapter order."""

from __future__ import annotations

from nosqlde.studio.lessons import ch01, ch02, ch03, ch04, ch05, ch06, ch07, ch08
from nosqlde.studio.lessons.model import Exercise, Lesson

LESSONS: dict[str, Lesson] = {m.LESSON.id: m.LESSON for m in (ch01, ch02, ch03, ch04, ch05, ch06, ch07, ch08)}


def find_exercise(exercise_id: str) -> tuple[Lesson, Exercise] | None:
    for lesson in LESSONS.values():
        x = lesson.exercise(exercise_id)
        if x is not None:
            return lesson, x
    return None
