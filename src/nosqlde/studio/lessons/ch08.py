"""Chapter 8 in the studio: the choosing-a-store quiz (no database)."""

from __future__ import annotations

from nosqlde.checks.ch08_choosing import KEY
from nosqlde.studio.lessons.model import GuideRef, Lesson
from nosqlde.studio.lessons.quiz import questions

LESSON = Lesson(
    id="ch08",
    number=8,
    title="Choosing a NoSQL database",
    database="no database",
    summary="Seven scenarios from the decision guide: pick the store, read why.",
    guide=GuideRef(8, "8. Choosing a NoSQL database"),
    quiz=questions("ch08_choosing.py", KEY),
)
