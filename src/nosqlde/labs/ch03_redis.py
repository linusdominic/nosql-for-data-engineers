"""Chapter 3 lab: Redis as a key-value store, and the jobs it does in a pipeline.

Run with `make lab-03` (Redis must be up: `make up-03`). The lab uses logical
database 3 and flushes it first. Step 3.3 changes the server's memory limit for a few
seconds and restores it; do not point this lab at a Redis you care about.
"""

from __future__ import annotations

import time
from typing import Any

import redis

from nosqlde import clients, datagen
from nosqlde.console import heading, say, step, table

DB = 3


STREAM, GROUP = "ch03:payments", "loader"


def load_structures(r: Any, world: datagen.World) -> Any:
    """Step 3.1's keys: a string, a counter, a hash, a list, two sets and a sorted set.
    Returns what LPOP took from the queue."""
    b = world.borrowers[0]
    r.set("ch03:loan:L0000006:status", "funded")
    r.incr("ch03:counter:applications_today")
    r.incrby("ch03:counter:applications_today", 41)
    r.hset(
        f"ch03:borrower:{b['borrower_id']}",
        mapping={"full_name": b["full_name"], "town": b["address"]["town"], "income": b["annual_income"]},
    )
    r.rpush("ch03:queue:documents_to_verify", "A0000001", "A0000002", "A0000003")
    first_in_queue = r.lpop("ch03:queue:documents_to_verify")
    r.sadd("ch03:phone:+999 7000:applications", "A0000030", "A0000302")
    r.sadd("ch03:device:dev-1:applications", "A0000302", "A0000413")
    for a in world.applications[:50]:
        r.zadd("ch03:scores", {a["application_id"]: a["_decision"]["score"]})
    return first_in_queue


def fill_stream(r: Any, events: list[dict[str, Any]], stream: str = STREAM, group: str = GROUP) -> None:
    """Step 3.8's stream: a consumer group, 20 payment entries and one poison entry."""
    r.xgroup_create(stream, group, id="0", mkstream=True)
    for e in events[:20]:
        r.xadd(
            stream, {"event_id": e["event_id"], "loan_id": e["loan_id"], "amount_cents": e["amount_cents"]}
        )
    r.xadd(stream, {"event_id": "poison", "loan_id": "L-BAD", "amount_cents": "not-a-number"})


def _wait(r: Any, field: str) -> None:
    """Wait until an INFO persistence flag (e.g. rdb_bgsave_in_progress) is 0."""
    for _ in range(100):
        if int(r.info("persistence")[field]) == 0:
            return
        time.sleep(0.05)


def run() -> None:
    heading("Chapter 3 lab: Redis")
    # Typed as Any: redis-py's return types are unions of sync and async results,
    # which only add noise to a lab.
    r: Any = clients.redis_client(DB)
    r.flushdb()
    world = datagen.generate(seed=42)

    # ------------------------------------------------------------------ 3.1
    step("3.1", "Five data structures, five SQL analogies")
    b = world.borrowers[0]
    first_in_queue = load_structures(r, world)
    shared = r.sinter("ch03:phone:+999 7000:applications", "ch03:device:dev-1:applications")
    top3 = r.zrevrange("ch03:scores", 0, 2, withscores=True)
    in_band = r.zcount("ch03:scores", 600, 700)
    rows = [
        ["string", "GET ch03:loan:L0000006:status", r.get("ch03:loan:L0000006:status"), "one cell"],
        ["string", "INCR / INCRBY counter", r.get("ch03:counter:applications_today"), "UPDATE .. SET n = n + 1"],
        ["hash", f"HGETALL ch03:borrower:{b['borrower_id']}", r.hgetall(f"ch03:borrower:{b['borrower_id']}"), "one row"],
        ["list", "LPOP queue (after RPUSH x3)", first_in_queue, "a FIFO queue table"],
        ["set", "SINTER phone-set device-set", sorted(shared), "INTERSECT"],
        ["sorted set", "ZREVRANGE scores 0 2", top3, "ORDER BY score DESC LIMIT 3"],
        ["sorted set", "ZCOUNT scores 600 700", in_band, "COUNT(*) WHERE score BETWEEN"],
    ]  # fmt: skip
    table(rows, ["type", "command", "result", "SQL analogy"])

    # ------------------------------------------------------------------ 3.2
    step("3.2", "Time to live (TTL)")
    r.set("ch03:session:abc", "cached-decision", ex=2)
    say(f"SET ch03:session:abc ... EX 2  ->  TTL = {r.ttl('ch03:session:abc')}s")
    say(f"TTL of a key with no expiry: {r.ttl('ch03:loan:L0000006:status')} (-1 means 'never expires')")
    time.sleep(2.2)
    say(
        f"after 2.2s: GET -> {r.get('ch03:session:abc')!r}, TTL -> {r.ttl('ch03:session:abc')} (-2 means 'no such key')"
    )

    # ------------------------------------------------------------------ 3.3
    step("3.3", "Running out of memory: noeviction versus allkeys-lru")
    original = r.config_get("maxmemory*")
    say(
        f"defaults: maxmemory={original['maxmemory']} (0 = no limit), maxmemory-policy={original['maxmemory-policy']}"
    )
    value = "x" * 1024
    step1_keys = [k for k in r.scan_iter("ch03:*") if not k.startswith("ch03:fill:")]
    try:
        used = int(r.info("memory")["used_memory"])
        r.config_set("maxmemory", used + 2 * 1024 * 1024)
        r.config_set("maxmemory-policy", "noeviction")
        written = 0
        try:
            for i in range(20_000):
                r.set(f"ch03:fill:{i}", value)
                written += 1
        except redis.exceptions.ResponseError as err:
            say(f"noeviction: wrote {written} x 1 KB keys, then the next SET failed: {str(err)[:60]}...")
        evicted_before = int(r.info("stats")["evicted_keys"])
        r.config_set("maxmemory-policy", "allkeys-lru")
        for i in range(written, written + 5_000):
            r.set(f"ch03:fill:{i}", value)
        evicted = int(r.info("stats")["evicted_keys"]) - evicted_before
        survivors = sum(1 for _ in r.scan_iter("ch03:fill:*", count=1000))
        step1_left = sum(1 for k in step1_keys if r.exists(k))
        say(
            f"allkeys-lru: wrote 5000 more keys; every write succeeded, Redis evicted {evicted} keys "
            f"to make room; {survivors} fill keys remain"
        )
        say(
            f"keys created in step 3.1 that survived: {step1_left} of {len(step1_keys)} "
            "(allkeys-* policies may evict any key, not only the ones you consider a cache)"
        )
    finally:
        r.config_set("maxmemory", original["maxmemory"])
        r.config_set("maxmemory-policy", original["maxmemory-policy"])
        for key in r.scan_iter("ch03:fill:*", count=1000):
            r.delete(key)
    say("restored maxmemory and maxmemory-policy to their defaults")

    # ------------------------------------------------------------------ 3.4
    step("3.4", "Persistence: RDB snapshots and the append-only file")
    cfg = {k: v for k, v in r.config_get("*").items() if k in ("save", "appendonly", "appendfsync")}
    say(f"CONFIG GET save/appendonly/appendfsync -> {cfg}")
    p = r.info("persistence")
    say(
        f"before BGSAVE: rdb_changes_since_last_save={p['rdb_changes_since_last_save']}, aof_enabled={p['aof_enabled']}"
    )
    r.bgsave()
    _wait(r, "rdb_bgsave_in_progress")
    p = r.info("persistence")
    say(
        f"after BGSAVE:  rdb_changes_since_last_save={p['rdb_changes_since_last_save']}, rdb_last_bgsave_status={p['rdb_last_bgsave_status']}"
    )
    r.config_set("appendonly", "yes")
    _wait(r, "aof_rewrite_in_progress")
    p = r.info("persistence")
    say(
        f"CONFIG SET appendonly yes -> aof_enabled={p['aof_enabled']}, aof_last_bgrewrite_status={p['aof_last_bgrewrite_status']}"
    )
    r.config_set("appendonly", "no")
    say("CONFIG SET appendonly no (back to the default)")

    # ------------------------------------------------------------------ 3.5
    step("3.5", "Cache-aside for a slow lookup")

    def slow_town_risk(town: str) -> str:
        time.sleep(0.01)  # pretend this is a 10 ms call to a reference-data service
        return "high" if town in ("Lowmarsh", "Cindervale") else "standard"

    apps = world.applications[:200]
    start = time.perf_counter()
    for a in apps:
        slow_town_risk(a["address"]["town"])
    uncached = time.perf_counter() - start
    hits = misses = 0
    start = time.perf_counter()
    for a in apps:
        key = f"ch03:cache:town_risk:{a['address']['town']}"
        cached = r.get(key)
        if cached is None:
            misses += 1
            r.set(key, slow_town_risk(a["address"]["town"]), ex=3600)
        else:
            hits += 1
    cached_time = time.perf_counter() - start
    say(f"200 lookups without a cache: {uncached:.2f}s")
    say(f"200 lookups with cache-aside: {cached_time:.2f}s ({misses} misses, {hits} hits)")

    # ------------------------------------------------------------------ 3.6
    step("3.6", "Idempotency keys: process each event once, even if it arrives twice")
    events = world.payments[:2_000]
    replayed = events + events[:300]  # an upstream retry re-sends the first 300
    naive_total = sum(e["amount_cents"] for e in replayed)
    processed = skipped = 0
    for e in replayed:
        # SET key value NX EX: set only if the key does not exist, with an expiry.
        if r.set(f"ch03:dedup:{e['event_id']}", 1, nx=True, ex=7 * 86_400):
            r.incrby("ch03:total_received_cents", e["amount_cents"])
            processed += 1
        else:
            skipped += 1
    true_total = sum(e["amount_cents"] for e in events)
    deduped_total = int(r.get("ch03:total_received_cents"))
    table(
        [
            ["events delivered", len(replayed)],
            ["processed (first time seen)", processed],
            ["skipped as duplicates", skipped],
            ["total without dedup (cents)", naive_total],
            ["total with dedup (cents)", deduped_total],
            ["true total (cents)", true_total],
        ],
        ["", "value"],
    )

    # ------------------------------------------------------------------ 3.7
    step("3.7", "Rate limiting with a fixed-window counter")

    def allow(client_id: str, limit: int = 10, window_s: int = 60) -> bool:
        key = f"ch03:rate:{client_id}:{int(time.time() // window_s)}"
        pipe = r.pipeline()  # MULTI ... EXEC: both commands run together
        pipe.incr(key)
        pipe.expire(key, window_s, nx=True)
        count, _ = pipe.execute()
        return int(count) <= limit

    decisions = [allow("broker-17") for _ in range(25)]
    say(
        f"25 calls from broker-17 with a limit of 10 per minute: {decisions.count(True)} allowed, {decisions.count(False)} rejected"
    )

    # ------------------------------------------------------------------ 3.8
    step("3.8", "Redis Streams with a consumer group: at-least-once delivery")
    stream, group = STREAM, GROUP
    fill_stream(r, events, stream, group)
    say(f"XADD 21 entries to {stream}; XGROUP CREATE {group}")
    batch_a = r.xreadgroup(group, "worker-a", {stream: ">"}, count=5)
    ids_a = [entry_id for entry_id, _ in batch_a[0][1]]
    say(f"worker-a read {len(ids_a)} entries and crashed before XACK")
    acked = 0
    while True:
        batch_b = r.xreadgroup(group, "worker-b", {stream: ">"}, count=10)
        if not batch_b:
            break
        for entry_id, fields in batch_b[0][1]:
            if fields["event_id"] == "poison":
                continue  # processing fails; leave it pending
            r.xack(stream, group, entry_id)
            acked += 1
    pending = r.xpending(stream, group)
    say(
        f"worker-b read the rest and acknowledged {acked}; XPENDING -> {pending['pending']} pending, consumers={pending['consumers']}"
    )
    time.sleep(1.1)
    claimed = r.xautoclaim(stream, group, "worker-b", min_idle_time=1000, start_id="0-0")
    claimed_ids = [entry_id for entry_id, _ in claimed[1]]
    detail = r.xpending_range(stream, group, min="-", max="+", count=10)
    say(f"after 1.1s idle, worker-b XAUTOCLAIMed {len(claimed_ids)} entries")
    table(
        [[d["message_id"], d["consumer"], d["times_delivered"]] for d in detail],
        ["entry id", "owner now", "times_delivered"],
    )
    for entry_id, fields in claimed[1]:
        if fields["event_id"] == "poison":
            continue
        r.xack(stream, group, entry_id)
    for _ in range(3):  # retry the poison message until it hits the delivery limit
        time.sleep(0.05)
        for d in r.xpending_range(stream, group, min="-", max="+", count=10):
            if d["times_delivered"] >= 3:
                entry = r.xrange(stream, d["message_id"], d["message_id"])[0][1]
                r.xadd("ch03:payments:dead_letter", {**entry, "reason": "failed 3 times"})
                r.xack(stream, group, d["message_id"])
            else:
                r.xclaim(stream, group, "worker-b", min_idle_time=0, message_ids=[d["message_id"]])
    pending = r.xpending(stream, group)
    say(
        f"processed the claimed entries; the poison entry was retried to 3 deliveries and moved to "
        f"ch03:payments:dead_letter ({r.xlen('ch03:payments:dead_letter')} entry). XPENDING -> {pending['pending']}"
    )
    info = r.xinfo_groups(stream)[0]
    say(f"XINFO GROUPS: entries-read={info['entries-read']}, lag={info['lag']}, pending={info['pending']}")
    r.close()
