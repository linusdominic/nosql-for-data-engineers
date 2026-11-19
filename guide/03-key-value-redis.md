# 3. Key-value with Redis

Time: about 1.5 hours (30 minutes reading, 20 minutes lab, 40 minutes exercises).

In the lesson studio (`make up-03`, then `make studio`): chapter 03, 8 exercises in a redis-cli console.

```bash
make up-03      # Redis 8.2.11 on localhost:6479
make lab-03
make check-03
make down
```

Statements in this chapter apply to Redis Open Source 8.2 (`redis:8.2.11-alpine`), run
with no configuration file, so every setting is the server's built-in default.

## What Redis is

Redis keeps all of its data in memory and serves it from a single thread that executes
one command at a time. That gives it two properties data engineers lean on:

- **Speed.** Reads and writes take microseconds on the server, so the network round
  trip usually dominates.
- **Atomic commands.** Because commands run one at a time, a single command such as
  `INCR` or `SET ... NX` can never interleave with another client's command. Many
  pipeline problems (deduplication, counters, locks) become one atomic command.

Every value lives under a **key**, a string you choose. There are no tables and no
queries by value: you get data by its key, so key naming is your schema. The convention
is colon-separated parts, `ch03:borrower:B000001`.

Redis also has 16 numbered **logical databases** (0 to 15) on one server; the lab uses
database 3 and the checks use 13 so they do not disturb each other.

## Data structures, mapped to SQL

Step 3.1 of `make lab-03` uses each of the core types:

```text
type        command                        result                                                                   SQL analogy
----------  -----------------------------  -----------------------------------------------------------------------  ----------------------------
string      GET ch03:loan:L0000006:status  funded                                                                   one cell
string      INCR / INCRBY counter          42                                                                       UPDATE .. SET n = n + 1
hash        HGETALL ch03:borrower:B000001  {'full_name': 'Hugo Ashcombe', 'town': 'Fernmouth', 'income': '157500'}  one row
list        LPOP queue (after RPUSH x3)    A0000001                                                                 a FIFO queue table
set         SINTER phone-set device-set    ['A0000302']                                                             INTERSECT
sorted set  ZREVRANGE scores 0 2           [('A0000004', 826.0), ('A0000039', 811.0), ('A0000018', 798.0)]          ORDER BY score DESC LIMIT 3
sorted set  ZCOUNT scores 600 700          20                                                                       COUNT(*) WHERE score BETWEEN
```

- **String:** any bytes up to 512 MB, plus atomic arithmetic (`INCR`, `INCRBY`).
- **Hash:** a small map of fields to values under one key. Note `'income': '157500'`:
  Redis stores strings, so types are your problem, as in chapter 2.
- **List:** an ordered sequence with fast push and pop at both ends.
- **Set:** unordered unique members, with intersections and unions.
- **Sorted set:** unique members each with a numeric score, kept ordered by score. The
  standard tool for leaderboards, time-ordered indexes and sliding windows.
- **Stream:** an append-only log with consumer groups, covered at the end of this chapter.

Redis 8 also bundles modules for JSON documents, search, time series and probabilistic
structures; `MODULE LIST` on this image shows `search`, `ReJSON`, `timeseries`, `bf` and
`vectorset`. This guide does not use them.

## Time to live

Any key can have a **TTL** (time to live): after it, the key is deleted. Step 3.2:

```text
SET ch03:session:abc ... EX 2  ->  TTL = 2s
TTL of a key with no expiry: -1 (-1 means 'never expires')
after 2.2s: GET -> None, TTL -> -2 (-2 means 'no such key')
```

Redis removes expired keys two ways: when a client touches an expired key, and with a
background job that samples keys with a TTL and deletes the expired ones. An expired key
is never returned, even if it has not yet been physically removed. TTLs are what make
Redis a good home for data that should disappear by itself: caches, sessions, idempotency
keys, rate-limit counters.

## Eviction: what happens when memory runs out

Redis data must fit in memory. `maxmemory` sets a limit and `maxmemory-policy` decides
what happens at the limit. The defaults, read from the server in step 3.3:

```text
defaults: maxmemory=0 (0 = no limit), maxmemory-policy=noeviction
```

`maxmemory=0` means "no limit" (on 64-bit builds), so the container's memory cap or the
operating system stops Redis instead. The lab sets a limit 2 MB above current use and
writes 1 KB values:

```text
noeviction: wrote 1569 x 1 KB keys, then the next SET failed: command not allowed when used memory > 'maxmemory'....
allkeys-lru: wrote 5000 more keys; every write succeeded, Redis evicted 5009 keys to make room; 1566 fill keys remain
keys created in step 3.1 that survived: 0 of 7 (allkeys-* policies may evict any key, not only the ones you consider a cache)
```

(The exact counts move by a few dozen between runs, because Redis's own memory use
varies. These are from one run.)

- **`noeviction`** rejects writes once full. Reads keep working. Safe for data you
  cannot lose, but your writers must handle the error.
- **`allkeys-lru`** evicts the least recently used keys, *any* keys. The lab's last line
  is the warning: the step 3.1 keys were the least recently used, so they went first.
  If a Redis instance holds both cache entries and pipeline state (dedup keys, stream
  entries), an `allkeys-*` policy can silently delete the state.
- **`volatile-*`** policies (`volatile-lru`, `volatile-lfu`, `volatile-ttl`,
  `volatile-random`) only evict keys that have a TTL, which lets one instance hold
  cache entries (with TTLs) next to keys that must stay. The trap: dedup keys usually
  carry a TTL too (this chapter's do), so a `volatile-*` policy can evict them. Keep
  pipeline state on a `noeviction` instance.

Redis's LRU is approximate: it samples a few keys (`maxmemory-samples`, default 5) and
evicts the best candidate among them, rather than tracking a perfect order.

## Persistence: RDB and AOF

Memory is lost when the process stops, so Redis can write data to disk two ways:

- **RDB snapshots:** a point-in-time dump. The `save` setting lists rules of the form
  "after N seconds, if at least M keys changed". The default `3600 1 300 100 60 10000`
  means: after an hour if 1 key changed, after 5 minutes if 100 changed, after a minute if
  10,000 changed. Anything written after the last snapshot is lost in a crash.
- **AOF (append-only file):** every write command is appended to a log, which is replayed
  on start. With `appendfsync everysec`, the log is flushed to disk once a second, so a
  crash loses about one second of writes.

Step 3.4 reads the defaults from this image and switches AOF on and off at runtime:

```text
CONFIG GET save/appendonly/appendfsync -> {'appendfsync': 'everysec', 'save': '3600 1 300 100 60 10000', 'appendonly': 'no'}
before BGSAVE: rdb_changes_since_last_save=14302, aof_enabled=0
after BGSAVE:  rdb_changes_since_last_save=0, rdb_last_bgsave_status=ok
CONFIG SET appendonly yes -> aof_enabled=1, aof_last_bgrewrite_status=ok
CONFIG SET appendonly no (back to the default)
```

So with the image's defaults, **AOF is off** and the only protection is RDB snapshots on
the schedule above. Treat a default Redis as a fast, mostly durable cache, not as the
system of record. (And remember the compose file has no volume: `make down` deletes the
snapshot too.)

## Data engineering uses

### Caching slow lookups (cache-aside)

**Cache-aside:** look in Redis first; on a miss, call the slow source and store the answer
with a TTL. Step 3.5 enriches 200 applications with a reference-data lookup that takes
10 ms per call:

```text
200 lookups without a cache: 2.57s
200 lookups with cache-aside: 0.15s (8 misses, 192 hits)
```

There are only 8 towns, so 8 calls miss and the rest are served from Redis. (Timings are
from one laptop.) The TTL decides how stale an answer may get; choose it from how often
the reference data changes, not from how much faster it makes the job.

### Idempotency keys: processing each event once

Most message systems deliver **at least once**: after a timeout or a retry, the same
event can arrive twice. A step is **idempotent** if doing it twice has the same effect as
doing it once. Inserting by primary key is idempotent; adding to a running total is not.

The standard fix is an **idempotency key**: `SET dedup:<event_id> 1 NX EX <ttl>` sets the
key only if it does not exist and returns whether it did. Because it is one atomic
command, two workers racing on the same event cannot both win. Step 3.6 replays 300 of
2,000 payment events:

```text
events delivered             2300
processed (first time seen)  2000
skipped as duplicates        300
total without dedup (cents)  152,790,584
total with dedup (cents)     133,237,006
true total (cents)           133,237,006
```

The TTL bounds memory: it must be longer than the longest gap after which a duplicate can
still arrive. One caveat, which the capstone comes back to: if the worker sets the
key and then crashes *before* doing the work, the event is never processed; if it does the
work and crashes *before* setting the key, it is processed twice. Pick the order that
fails safely for your side effect, and reconcile.

### Rate limiting

A **fixed-window counter** counts calls per client per minute: `INCR rate:<client>:<minute>`,
with an expiry set on the first call. Step 3.7 allows 10 calls a minute:

```text
25 calls from broker-17 with a limit of 10 per minute: 10 allowed, 15 rejected
```

The `INCR` and the `EXPIRE ... NX` run in one `MULTI`/`EXEC` transaction through a
pipeline, so a crash between them cannot leave a counter without an expiry. A fixed
window allows a burst at the boundary (10 calls at 12:00:59 and 10 more at 12:01:00); a
sliding window built on a sorted set (`ZADD` the timestamp, `ZREMRANGEBYSCORE` the old
ones, `ZCARD`) avoids that at the cost of more memory.

### Redis Streams with consumer groups as a lightweight queue

A **stream** is an append-only log of entries, each with an id like `1795094114907-0`
(milliseconds, sequence) and a small map of fields. A **consumer group** lets several
workers share a stream: each entry goes to one consumer in the group. Redis remembers,
per group, which entries were delivered and not yet acknowledged, in the **pending
entries list (PEL)**.

- `XADD` appends an entry.
- `XREADGROUP GROUP g worker-a STREAMS s >` delivers entries no one in the group has
  received yet, and records them as pending for `worker-a`.
- `XACK` removes an entry from the PEL once it has been processed.
- `XPENDING` shows what is pending, for whom, and how many times it has been delivered.
- `XAUTOCLAIM` (or `XCLAIM`) transfers entries that have been idle too long to another
  consumer. **Redis never redelivers by itself**: if nobody claims a dead worker's
  entries, they sit in the PEL forever.

Step 3.8 plays a full failure:

```text
XADD 21 entries to ch03:payments; XGROUP CREATE loader
worker-a read 5 entries and crashed before XACK
worker-b read the rest and acknowledged 15; XPENDING -> 6 pending, consumers=[{'name': 'worker-a', 'pending': 5}, {'name': 'worker-b', 'pending': 1}]
after 1.1s idle, worker-b XAUTOCLAIMed 6 entries
entry id         owner now  times_delivered
---------------  ---------  ---------------
1795094114907-0  worker-b   2
1795094114907-1  worker-b   2
1795094114908-0  worker-b   2
1795094114908-1  worker-b   2
1795094114908-2  worker-b   2
1795094114910-1  worker-b   2
processed the claimed entries; the poison entry was retried to 3 deliveries and moved to ch03:payments:dead_letter (1 entry). XPENDING -> 0
XINFO GROUPS: entries-read=21, lag=0, pending=0
```

(Entry ids are timestamps, so yours will differ.)

What happened: worker-a's 5 entries were never acknowledged. worker-b processed the other
15, but one entry is a **poison message** that fails every time, so it stayed pending
too. After the idle time, worker-b claimed all 6 (`times_delivered` went to 2) and
processed the 5 good ones. The poison entry was retried until it had been delivered 3
times, then copied to a **dead-letter stream** and acknowledged, so it stops blocking the
group and a human can look at it.

This is **at-least-once delivery**: every entry is processed, some more than once, which
is why the consumer must be idempotent (the previous section). Two more operational
points: streams grow until you trim them (`XADD ... MAXLEN ~ 1000000` or `XTRIM`), and
they live in memory and are persisted with RDB/AOF like everything else in Redis, so the
persistence settings above decide how much of the queue survives a crash. For a durable,
replayable event log at scale, Kafka or a managed queue is the usual choice; Redis
Streams fit small to medium pipelines that already have Redis.

## Exercises

`exercises/ch03_redis.py`:

1. `get_or_load`: cache-aside with a TTL.
2. `process_once`: an idempotency key that survives 8 racing threads.
3. `allow_request`: a fixed-window rate limiter whose counters expire.
4. `consume`: an at-least-once stream consumer that claims stale entries and leaves
   failures pending.

```bash
make check-03
```

```text
Checking solutions/ch03_redis.py
  PASS  3.1 get_or_load: loader called once, value cached with a TTL
  PASS  3.2 process_once: True once, then False; 8 racing workers -> exactly 1 winner
  PASS  3.3 allow_request: 5 allowed, 3 rejected, per-client budgets, counters expire
  PASS  3.4 consume: claimed 3 stale entries, read 8 new, acked 10, left the failing one pending

Chapter 3 (Redis): 4/4 passed (checked solutions/ch03_redis.py)
```

## What is not verified

- Data loss on a crash with the default persistence settings is described from the
  configuration, not demonstrated by killing the container.
- Replication, Sentinel and Redis Cluster are not covered; every statement about
  failover is from the documentation, not from a test here.
- Eviction counts vary by a few dozen between runs, and cache timings are from one
  laptop; neither is a benchmark.

## Further reading

- [Redis data types](https://redis.io/docs/latest/develop/data-types/)
- [Key eviction](https://redis.io/docs/latest/develop/reference/eviction/)
- [Persistence](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)
- [EXPIRE and how keys expire](https://redis.io/docs/latest/commands/expire/)
- [Streams introduction](https://redis.io/docs/latest/develop/data-types/streams/) and
  [XAUTOCLAIM](https://redis.io/docs/latest/commands/xautoclaim/)
