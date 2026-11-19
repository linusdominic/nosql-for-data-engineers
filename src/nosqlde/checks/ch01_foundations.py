"""Check chapter 1's quiz (no database needed)."""

from __future__ import annotations

from nosqlde.checks.quiz import run_quiz

KEY = {
    "1.1": ("b", "Lookup by id plus expiry is exactly what a key-value store with TTLs does."),
    "1.2": ("b", "Accepting writes on both sides keeps the system available but lets the sides disagree."),
    "1.3": (
        "b",
        "Even without a partition, waiting for more replicas costs latency; not waiting risks stale reads.",
    ),
    "1.4": (
        "c",
        "Eventual consistency only promises replicas converge later; this read may hit a stale one.",
    ),
    "1.5": ("c", "Unplanned joins across entities are what SQL and a normalised schema are built for."),
    "1.6": ("b", "These stores serve queries by key; the primary key decides what can be read cheaply."),
}


def run(solutions: bool = False) -> int:
    return run_quiz("Chapter 1 (foundations quiz)", "ch01_foundations.py", solutions, KEY)
