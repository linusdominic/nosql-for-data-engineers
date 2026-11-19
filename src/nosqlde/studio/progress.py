"""Progress in .studio/progress.json (git-ignored): attempts, passes, quiz answers.

One learner, one file. Writes are atomic (temporary file, then rename) and serialised
with a lock, so a crash never leaves half a file.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

VERSION = 1


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Progress:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            data: Any = json.loads(self.path.read_text())
            if isinstance(data, dict) and data.get("version") == VERSION:
                data.setdefault("exercises", {})
                data.setdefault("quizzes", {})
                data.setdefault("prepared", {})
                loaded: dict[str, Any] = data
                return loaded
        except (OSError, ValueError):
            pass
        return {"version": VERSION, "exercises": {}, "quizzes": {}, "prepared": {}}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".progress-", suffix=".json")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(self._data, fh, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            copy: dict[str, Any] = json.loads(json.dumps(self._data))
            return copy

    def exercise(self, exercise_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._data["exercises"].get(exercise_id, {}))

    def record_attempt(self, exercise_id: str, answer: str, ok: bool) -> dict[str, Any]:
        with self._lock:
            entry = self._data["exercises"].setdefault(exercise_id, {"attempts": 0, "passed": False})
            entry["attempts"] = int(entry.get("attempts", 0)) + 1
            entry["last_answer"] = answer[:20_000]
            entry["last_attempt_at"] = _now()
            if ok:
                if not entry.get("passed"):
                    entry["passed_at"] = _now()
                entry["passed"] = True
            self._save()
            return dict(entry)

    def record_reveal(self, exercise_id: str) -> None:
        with self._lock:
            entry = self._data["exercises"].setdefault(exercise_id, {"attempts": 0, "passed": False})
            entry["solution_shown"] = True
            self._save()

    def record_quiz(self, lesson_id: str, answers: dict[str, str], correct: dict[str, bool]) -> None:
        with self._lock:
            quiz = self._data["quizzes"].setdefault(lesson_id, {})
            for qid, letter in answers.items():
                quiz[qid] = {"answer": letter, "correct": bool(correct.get(qid))}
            self._save()

    def record_prepared(self, lesson_id: str, seconds: float) -> None:
        with self._lock:
            self._data["prepared"][lesson_id] = {"at": _now(), "seconds": seconds}
            self._save()

    def reset(self, lesson_id: str | None = None) -> None:
        with self._lock:
            if lesson_id is None:
                self._data = {"version": VERSION, "exercises": {}, "quizzes": {}, "prepared": {}}
            else:
                prefix = f"{lesson_id}."
                self._data["exercises"] = {
                    k: v for k, v in self._data["exercises"].items() if not k.startswith(prefix)
                }
                self._data["quizzes"].pop(lesson_id, None)
            self._save()
