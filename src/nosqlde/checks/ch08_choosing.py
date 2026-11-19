"""Check chapter 8's quiz (no database needed)."""

from __future__ import annotations

from nosqlde.checks.quiz import run_quiz

KEY = {
    "8.1": ("a", "Multi-row ACID postings and unplanned reporting are what relational databases are for."),
    "8.2": (
        "c",
        "High write rates, multi-region, and reads by partition (device) and clustering (time) fit Cassandra.",
    ),
    "8.3": ("b", "Variable-length traversals over relationships are the graph database's home ground."),
    "8.4": ("b", "DynamoDB is fully managed and rewards known access patterns."),
    "8.5": ("a", "Varied nested documents, secondary indexes and transactions describe MongoDB."),
    "8.6": ("b", "By default the image snapshots with RDB and has AOF off, so recent writes can be lost."),
    "8.7": ("c", "Relevance ranking and fuzzy matching need an inverted index: a search engine."),
}


def run(solutions: bool = False) -> int:
    return run_quiz("Chapter 8 (choosing a store quiz)", "ch08_choosing.py", solutions, KEY)
