"""Check chapter 3's exercises against Redis (logical database 13, flushed first)."""

from __future__ import annotations

import threading
import time
from typing import Any

from nosqlde import checks, clients

DB = 13


def run(solutions: bool = False) -> int:
    checker, answers = checks.start("Chapter 3 (Redis)", "ch03_redis.py", solutions)
    r = clients.redis_client(DB)
    r.flushdb()

    def ex1() -> str:
        calls = []

        def loader() -> str:
            calls.append(1)
            return "grade-B"

        first = answers.get_or_load(r, "cache:x", loader, 60)
        second = answers.get_or_load(r, "cache:x", loader, 60)
        assert first == second == "grade-B", f"expected 'grade-B' twice, got {first!r}, {second!r}"
        assert len(calls) == 1, f"the loader should run once, it ran {len(calls)} times"
        ttl = r.ttl("cache:x")
        assert 0 < ttl <= 60, f"the cached key should expire within 60s, TTL is {ttl}"
        return "loader called once, value cached with a TTL"

    def ex2() -> str:
        assert answers.process_once(r, "evt-1", 60) is True, "first call should return True"
        assert answers.process_once(r, "evt-1", 60) is False, "second call should return False"
        ttl = r.ttl("dedup:evt-1")
        assert 0 < ttl <= 60, f"key dedup:evt-1 should have a TTL <= 60, got {ttl}"
        results: list[bool] = []
        barrier = threading.Barrier(8)

        def race() -> None:
            local = clients.redis_client(DB)
            barrier.wait()
            results.append(bool(answers.process_once(local, "evt-race", 60)))

        threads = [threading.Thread(target=race) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert results.count(True) == 1, (
            f"8 workers raced on one event and {results.count(True)} got True; it must be exactly 1. "
            "Use one atomic command (SET with NX), not GET followed by SET."
        )
        return "True once, then False; 8 racing workers -> exactly 1 winner"

    def ex3() -> str:
        allowed = [answers.allow_request(r, "c1", 5, 60) for _ in range(8)]
        assert allowed == [True] * 5 + [False] * 3, f"limit 5: expected 5 True then 3 False, got {allowed}"
        other = answers.allow_request(r, "c2", 5, 60)
        assert other is True, "a different client has its own budget"
        keys = [k for k in r.scan_iter("*") if "c1" in k]
        assert keys, "expected a counter key containing the client id"
        ttls = [r.ttl(k) for k in keys]
        assert all(0 < t <= 60 for t in ttls), f"counter keys must expire (TTLs: {ttls})"
        return "5 allowed, 3 rejected, per-client budgets, counters expire"

    def ex4() -> str:
        stream, group = "check:stream", "g"
        r.delete(stream)
        r.xgroup_create(stream, group, id="0", mkstream=True)
        for i in range(10):
            r.xadd(stream, {"n": str(i)})
        r.xadd(stream, {"n": "bad"})
        r.xreadgroup(group, "dead-worker", {stream: ">"}, count=3)  # never acked
        time.sleep(0.15)
        seen: list[str] = []

        def handler(fields: dict[str, Any]) -> None:
            if fields["n"] == "bad":
                raise ValueError("cannot parse")
            seen.append(fields["n"])

        acked = answers.consume(r, stream, group, "worker", handler, 100)
        assert acked == 10, f"expected 10 entries acknowledged, got {acked}"
        assert sorted(seen, key=int) == [str(i) for i in range(10)], (
            f"handler should have seen 0..9 (including the 3 the dead worker held), saw {seen}"
        )
        pending = r.xpending(stream, group)
        assert pending["pending"] == 1, (
            f"only the failing entry should stay pending, got {pending['pending']}"
        )
        return "claimed 3 stale entries, read 8 new, acked 10, left the failing one pending"

    checker.run("3.1 get_or_load", ex1)
    checker.run("3.2 process_once", ex2)
    checker.run("3.3 allow_request", ex3)
    checker.run("3.4 consume", ex4)
    r.flushdb()
    return checker.finish()
