"""Chapters 1 and 8 are quizzes. The studio reuses them as they are: the questions and
options come from the comments in exercises/ch01_foundations.py and ch08_choosing.py, the
answers and explanations from the KEY in nosqlde.checks."""

from __future__ import annotations

import re
from pathlib import Path

from nosqlde.studio.lessons.model import QuizQuestion
from nosqlde.studio.paths import repo_root

_QUESTION = re.compile(r"^\s*#\s+(\d+\.\d+)\s+(.*)$")
_CONTINUATION = re.compile(r"^\s*#\s{2,}(.*)$")
_OPTION = re.compile(r"(?:^|\s)([a-d])\)\s+")


def parse_questions(path: Path, key: dict[str, tuple[str, str]]) -> tuple[QuizQuestion, ...]:
    """Questions from an exercises file's comments, with the answer key from checks."""
    text: dict[str, list[str]] = {}
    current: str | None = None
    for line in path.read_text().splitlines():
        m = _QUESTION.match(line)
        if m and m.group(1) in key:
            current = m.group(1)
            text[current] = [m.group(2).strip()]
            continue
        if current:
            c = _CONTINUATION.match(line)
            if c:
                text[current].append(c.group(1).strip())
            else:
                current = None
    out = []
    for qid, (answer, why) in key.items():
        if qid not in text:
            raise ValueError(f"question {qid} not found in {path}")
        joined = " ".join(text[qid])
        first = _OPTION.search(joined)
        if first is None:
            raise ValueError(f"question {qid} in {path} has no a) ... options")
        question = joined[: first.start()].strip()
        parts = _OPTION.split(joined[first.start() :])
        # parts: ['', 'a', 'text', 'b', 'text', ...]
        options = tuple((parts[i], parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2))
        out.append(QuizQuestion(qid, question, options, answer, why))
    return tuple(out)


def questions(filename: str, key: dict[str, tuple[str, str]]) -> tuple[QuizQuestion, ...]:
    return parse_questions(repo_root() / "exercises" / filename, key)
