"""Chapter 1 in the studio: the foundations quiz (no database)."""

from __future__ import annotations

from nosqlde.checks.ch01_foundations import KEY
from nosqlde.studio.lessons.model import GuideRef, Lesson
from nosqlde.studio.lessons.quiz import questions

LESSON = Lesson(
    id="ch01",
    number=1,
    title="Why NoSQL exists",
    database="no database",
    summary="Families, CAP and PACELC, consistency models, and when not to use NoSQL: the chapter's six-question quiz.",
    guide=GuideRef(1, "1. Why NoSQL exists"),
    quiz=questions("ch01_foundations.py", KEY),
)
