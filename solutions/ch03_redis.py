"""Chapter 3 reference solutions: Redis. Check them with `make check-03 SOLUTIONS=1`."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import redis


def get_or_load(r: redis.Redis, key: str, loader: Callable[[], str], ttl_seconds: int) -> str:
    cached = r.get(key)
    if cached is not None:
        return str(cached)
    value = loader()
    r.set(key, value, ex=ttl_seconds)
    return value


def process_once(r: redis.Redis, event_id: str, ttl_seconds: int) -> bool:
    # SET ... NX EX is one atomic command: check-and-set cannot race.
    return bool(r.set(f"dedup:{event_id}", 1, nx=True, ex=ttl_seconds))


def allow_request(r: redis.Redis, client_id: str, limit: int, window_seconds: int) -> bool:
    window = int(time.time() // window_seconds)
    key = f"rate:{client_id}:{window}"
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, window_seconds, nx=True)
    count, _ = pipe.execute()
    return int(count) <= limit


def _handle(
    r: redis.Redis, stream: str, group: str, entries: list[Any], handler: Callable[[dict[str, str]], None]
) -> int:
    acked = 0
    for entry_id, fields in entries:
        try:
            handler(fields)
        except Exception:
            continue  # stays pending; a later run (or another consumer) retries it
        r.xack(stream, group, entry_id)
        acked += 1
    return acked


def consume(
    r: redis.Redis,
    stream: str,
    group: str,
    consumer: str,
    handler: Callable[[dict[str, str]], None],
    min_idle_ms: int,
) -> int:
    acked = 0
    start = "0-0"
    while True:
        claimed: Any = r.xautoclaim(stream, group, consumer, min_idle_time=min_idle_ms, start_id=start)
        acked += _handle(r, stream, group, claimed[1], handler)
        start = claimed[0]
        if start == "0-0":
            break
    while True:
        batch: Any = r.xreadgroup(group, consumer, {stream: ">"}, count=100)
        if not batch:
            break
        acked += _handle(r, stream, group, batch[0][1], handler)
    return acked
