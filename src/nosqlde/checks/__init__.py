"""Check commands: run the reader's exercise answers against a live database.

`nosqlde check 02` imports `exercises/ch02_mongodb.py`, calls each function the
chapter asks for, and prints PASS or FAIL with a hint. `--solutions` checks the
reference answers in `solutions/` instead, which is what CI and the test-suite do.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

from nosqlde.clients import ServiceUnavailable


def repo_root() -> Path:
    """The folder that holds exercises/ and solutions/ (the current directory by default)."""
    return Path(os.environ.get("NOSQLDE_ROOT", Path.cwd()))


def load_answers(filename: str, solutions: bool) -> ModuleType:
    """Import exercises/<filename> (or solutions/<filename>) by path."""
    folder = "solutions" if solutions else "exercises"
    path = repo_root() / folder / filename
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run checks from the repository root.")
    name = f"nosqlde_answers_{folder}_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class Result:
    name: str
    ok: bool
    detail: str
    seconds: float


@dataclass
class Checker:
    """Collects PASS/FAIL results for one chapter and prints them."""

    title: str
    source: str
    results: list[Result] = field(default_factory=list)

    def run(self, name: str, fn: Callable[[], str]) -> None:
        start = time.perf_counter()
        try:
            detail = fn()
            ok = True
        except NotImplementedError:
            ok, detail = False, "not implemented yet (the function still raises NotImplementedError)"
        except AssertionError as err:
            ok, detail = False, str(err) or "assertion failed"
        except ServiceUnavailable:
            raise
        except Exception as err:  # the reader's code raised: show where
            tb = traceback.extract_tb(err.__traceback__)[-1]
            where = f"{Path(tb.filename).name}:{tb.lineno}"
            ok, detail = False, f"{type(err).__name__} at {where}: {err}"
        self.results.append(Result(name, ok, detail, time.perf_counter() - start))
        mark = "PASS" if ok else "FAIL"
        print(f"  {mark}  {name}: {detail}")

    def finish(self) -> int:
        passed = sum(r.ok for r in self.results)
        total = len(self.results)
        print(f"\n{self.title}: {passed}/{total} passed (checked {self.source})")
        if passed < total:
            print("Edit the file above and run the check again. Stuck? Compare with solutions/.")
        return 0 if passed == total else 1


def start(title: str, filename: str, solutions: bool) -> tuple[Checker, ModuleType]:
    folder = "solutions" if solutions else "exercises"
    print(f"Checking {folder}/{filename}")
    return Checker(title, f"{folder}/{filename}"), load_answers(filename, solutions)
