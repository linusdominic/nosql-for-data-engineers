"""Chapter 1 exercises: a short quiz on the ideas in guide/01-why-nosql.md.

Replace each None with the letter of your answer, then run `make check-01`.
No database is needed. A wrong answer prints an explanation.
"""

from __future__ import annotations

ANSWERS: dict[str, str | None] = {
    # 1.1 A pipeline must remember which event ids it has processed in the last 7 days,
    #     with lookups by id only and automatic expiry. Which family fits best?
    #     a) document  b) key-value  c) graph  d) wide-column
    "1.1": None,
    # 1.2 During a network partition, a replicated database keeps accepting writes on
    #     both sides of the split. In CAP terms it has chosen:
    #     a) consistency  b) availability  c) partition tolerance  d) none of these
    "1.2": None,
    # 1.3 The "ELC" in PACELC says that when there is NO partition, a system still trades:
    #     a) cost against durability  b) latency against consistency
    #     c) availability against durability  d) nothing; there is no trade-off then
    "1.3": None,
    # 1.4 A borrower changes their address and immediately reloads the page. The read
    #     goes to a replica under eventual consistency. What can they see?
    #     a) only the new address  b) an error  c) possibly the old address
    #     d) both addresses
    "1.4": None,
    # 1.5 Which requirement is the strongest reason to stay on a relational database?
    #     a) millions of writes per second  b) flexible, nested documents
    #     c) new ad-hoc questions that join many entities in ways nobody planned
    #     d) values that expire automatically
    "1.5": None,
    # 1.6 In Cassandra or DynamoDB, what mostly decides which queries are cheap?
    #     a) the indexes added after go-live  b) the primary key chosen up front
    #     c) the size of the cluster  d) the client library
    "1.6": None,
}
