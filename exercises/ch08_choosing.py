"""Chapter 8 exercises: choosing a store. Replace each None with a letter, then run
`make check-08`. No database is needed. A wrong answer prints an explanation.
"""

from __future__ import annotations

ANSWERS: dict[str, str | None] = {
    # 8.1 The loan ledger: balances must never be wrong, postings touch several rows
    #     atomically, and finance writes new reports every month.
    #     a) a relational database  b) Redis  c) Cassandra  d) Neo4j
    "8.1": None,
    # 8.2 Device telemetry from a mobile app: 50,000 events a second, always read by
    #     device and time range, written in three regions.
    #     a) a relational database  b) Neo4j  c) Cassandra  d) Redis
    "8.2": None,
    # 8.3 "Show every application within four hops of this one through shared phones,
    #     devices or addresses", interactively, for an investigator.
    #     a) DynamoDB  b) Neo4j  c) Redis  d) Cassandra
    "8.3": None,
    # 8.4 A small team on AWS wants a key-value/document store with no servers to
    #     patch, and they know their access patterns up front.
    #     a) self-managed Cassandra  b) DynamoDB  c) Neo4j on EC2  d) Redis on a VM
    "8.4": None,
    # 8.5 Application documents whose shape varies by product and channel, queried by
    #     several fields, with occasional multi-document transactions.
    #     a) MongoDB  b) Redis  c) Cassandra  d) a search engine
    "8.5": None,
    # 8.6 A team keeps the only copy of loan decisions in Redis running with the image's
    #     default configuration. What is the main risk?
    #     a) slow reads  b) writes after the last RDB snapshot are lost if Redis stops
    #     c) keys cannot have TTLs  d) Redis cannot store hashes
    "8.6": None,
    # 8.7 Free-text search over collections notes, ranked by relevance, with typo
    #     tolerance.
    #     a) Cassandra  b) DynamoDB  c) a search engine such as OpenSearch  d) Redis lists
    "8.7": None,
}
