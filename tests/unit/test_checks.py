"""Checks that need no database: quizzes and the capstone's pure exercises."""

from __future__ import annotations

from pathlib import Path

import pytest

from nosqlde import checks, cli
from nosqlde.checks import ch01_foundations, ch08_choosing

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOSQLDE_ROOT", str(ROOT))


@pytest.mark.parametrize("module", [ch01_foundations, ch08_choosing])
def test_quiz_solutions_pass_and_starters_fail(module: object, capsys: pytest.CaptureFixture[str]) -> None:
    assert module.run(solutions=True) == 0  # type: ignore[attr-defined]
    assert module.run(solutions=False) == 1  # type: ignore[attr-defined]
    assert "not implemented yet" in capsys.readouterr().out


def test_every_exercise_has_a_solution_with_the_same_functions() -> None:
    for exercise in sorted((ROOT / "exercises").glob("ch*.py")):
        solution = ROOT / "solutions" / exercise.name
        assert solution.exists(), f"missing {solution}"
        ex = checks.load_answers(exercise.name, solutions=False)
        so = checks.load_answers(exercise.name, solutions=True)
        public = {
            n
            for n in vars(ex)
            if not n.startswith("_") and callable(getattr(ex, n)) and getattr(ex, n).__module__ == ex.__name__
        }
        for name in public:
            assert callable(getattr(so, name, None)), f"{solution.name} lacks {name}()"


def test_capstone_pure_exercises_pass_with_solutions() -> None:
    so = checks.load_answers("ch07_capstone.py", solutions=True)
    assert so.dpd_bucket(45) == "30-59"
    assert so.order_independent_checksum([(1,), (2,)]) == so.order_independent_checksum([(2,), (1,)])


def test_cli_datagen(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["datagen"]) == 0
    out = capsys.readouterr().out
    assert "applications" in out and "2393" in out


def test_cli_rejects_unknown_chapter() -> None:
    with pytest.raises(SystemExit):
        cli.main(["lab", "42"])
