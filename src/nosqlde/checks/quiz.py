"""Shared logic for the quiz chapters (1 and 8): compare letters, explain mistakes."""

from __future__ import annotations

from nosqlde import checks


def run_quiz(title: str, filename: str, solutions: bool, key: dict[str, tuple[str, str]]) -> int:
    checker, answers = checks.start(title, filename, solutions)
    given: dict[str, str | None] = getattr(answers, "ANSWERS", {})
    for qid, (correct, why) in key.items():

        def one(qid: str = qid, correct: str = correct, why: str = why) -> str:
            answer = given.get(qid)
            if answer is None:
                raise NotImplementedError
            assert str(answer).strip().lower() == correct, f"you answered {answer!r}. {why}"
            return why

        checker.run(f"question {qid}", one)
    return checker.finish()
