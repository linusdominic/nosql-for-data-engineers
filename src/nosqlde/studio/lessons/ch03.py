"""Chapter 3 in the studio: Redis, in a redis-cli console (logical database 5)."""

from __future__ import annotations

from typing import Any

from nosqlde.studio.checking import CheckRun, Outcome, failed, passed
from nosqlde.studio.lessons.model import Custom, Example, Exercise, GuideRef, Lesson, Match, Step
from nosqlde.studio.lessons.prepare import prepare_redis
from nosqlde.studio.runners.base import RunResult

RESET_GROUP = "XGROUP DESTROY ch03:payments loader\nXGROUP CREATE ch03:payments loader 0"


def _replies(run: CheckRun, text: str) -> list[Any]:
    result = run.run(text)
    return [b.data for b in result.blocks]


def check_session_ttl(run: CheckRun, answer: RunResult) -> Outcome:
    value, ttl = _replies(run, "GET ch03:session:me\nTTL ch03:session:me")
    expected = {"GET": "cached-decision", "TTL": "1 to 60"}
    got = {"GET": value, "TTL": ttl}
    if value != "cached-decision":
        return failed("GET ch03:session:me does not return cached-decision.", expected, got)
    if not isinstance(ttl, int) or ttl == -1:
        return failed(
            "The key never expires (TTL -1). Give it the expiry in the same SET command.", expected, got
        )
    if not 0 < ttl <= 60:
        return failed(f"The key expires in {ttl} seconds; the task asks for 60.", expected, got)
    return passed(f"Stored with an expiry: TTL {ttl}s. Redis will delete it by itself.", expected, got)


def check_volatile_lru(run: CheckRun, answer: RunResult) -> Outcome:
    reply = _replies(run, "CONFIG GET maxmemory-policy")[0]
    run.setup("CONFIG SET maxmemory-policy noeviction")  # back to the image's default
    policy = reply[1] if isinstance(reply, list) and len(reply) == 2 else reply
    expected = {"maxmemory-policy": "volatile-lru"}
    got = {"maxmemory-policy": policy}
    if policy == "volatile-lru":
        return passed(
            "volatile-lru evicts only keys with a TTL, least recently used first. (The check set the policy back to noeviction.)",
            expected,
            got,
        )
    if isinstance(policy, str) and policy.startswith("allkeys"):
        return failed(f"{policy} may evict any key, including the ones that must stay.", expected, got)
    return failed(
        f"The policy is {policy}; the task asks for the one that evicts only keys with a TTL, by least recent use.",
        expected,
        got,
    )


def check_dedup(run: CheckRun, answer: RunResult) -> Outcome:
    first = answer.last.data if answer.last else None
    second_result = run.run(run.answer)
    second = second_result.last.data if second_result.last else None
    ttl = _replies(run, "TTL ch03:dedup:evt-42")[0]
    expected = {"first delivery": "OK", "second delivery": None, "TTL": "1 to 604800"}
    got = {"first delivery": first, "second delivery": second, "TTL": ttl}
    if first not in ("OK", 1):
        return failed("The first delivery of evt-42 was not recorded.", expected, got)
    if second not in (None, 0):
        return failed(
            "The check ran your command a second time (a duplicate delivery) and it succeeded again: the event would be processed twice. Set the key only if it does not exist.",
            expected,
            got,
        )
    if not isinstance(ttl, int) or ttl <= 0:
        return failed(
            "The dedup key never expires, so the set of keys grows forever. Give it an expiry of 7 days.",
            expected,
            got,
        )
    if ttl > 604_800:
        return failed(f"The key expires in {ttl} seconds; 7 days is 604800.", expected, got)
    return passed(
        "First delivery recorded, the duplicate refused, the key expires in 7 days: one atomic SET ... NX EX.",
        expected,
        got,
    )


def check_rate_limit(run: CheckRun, answer: RunResult) -> Outcome:
    exec_reply = answer.last.data if answer.last else None
    value, ttl = _replies(run, "GET ch03:rate:broker-17:demo\nTTL ch03:rate:broker-17:demo")
    second = run.run(run.answer)
    second_exec = second.last.data if second.last else None
    expected = {"EXEC (first call)": [1, 1], "EXEC (second call)": [2, 0], "TTL": "1 to 60"}
    got = {"EXEC (first call)": exec_reply, "EXEC (second call)": second_exec, "TTL": ttl}
    if not isinstance(exec_reply, list):
        return failed(
            "The last command should be EXEC, returning both replies: wrap INCR and EXPIRE in MULTI ... EXEC.",
            expected,
            got,
        )
    if value != "1":
        return failed("After one call the counter should be 1.", expected, got)
    if not isinstance(ttl, int) or not 0 < ttl <= 60:
        return failed("The counter must expire within 60 seconds, or old windows pile up.", expected, got)
    if not isinstance(second_exec, list) or len(second_exec) < 2 or second_exec[0] != 2:
        return failed("A second call should increment the same counter to 2.", expected, got)
    if second_exec[1] != 0:
        return failed(
            "The second call reset the expiry, so a busy client's window never ends. Only set it when the key has none: EXPIRE ... NX.",
            expected,
            got,
        )
    return passed(
        "Counter 1 then 2 in one window, expiry set once: INCR and EXPIRE ... NX in MULTI/EXEC.",
        expected,
        got,
    )


def _pending(run: CheckRun) -> tuple[int, list[list[str]]]:
    reply = _replies(run, "XPENDING ch03:payments loader")[0]
    if not isinstance(reply, list) or not reply:
        return 0, []
    count = int(reply[0])
    consumers = reply[3] if len(reply) > 3 and isinstance(reply[3], list) else []
    return count, sorted(consumers)


def check_readgroup(run: CheckRun, answer: RunResult) -> Outcome:
    count, consumers = _pending(run)
    expected = {"pending": 5, "consumers": [["worker-a", "5"]]}
    got = {"pending": count, "consumers": consumers}
    if consumers == [["worker-a", "5"]]:
        return passed(
            "worker-a holds 5 delivered, unacknowledged entries in the group's pending entries list.",
            expected,
            got,
        )
    if count == 0:
        return failed(
            "Nothing is pending for the group: XREAD (without a group) or an id other than > does not deliver new entries to a consumer.",
            expected,
            got,
        )
    return failed("The pending entries list is not 5 entries for worker-a.", expected, got)


def check_autoclaim(run: CheckRun, answer: RunResult) -> Outcome:
    _, consumers = _pending(run)
    detail = _replies(run, "XPENDING ch03:payments loader - + 10")[0]
    deliveries = sorted({int(d[3]) for d in detail}) if isinstance(detail, list) else []
    expected = {"consumers": [["worker-b", "5"]], "times_delivered": [2]}
    got = {"consumers": consumers, "times_delivered": deliveries}
    if consumers == [["worker-b", "5"]] and deliveries == [2]:
        return passed(
            "worker-b now owns worker-a's 5 entries; each has been delivered twice. Redis never redelivers by itself.",
            expected,
            got,
        )
    if ["worker-a", "5"] in consumers:
        return failed("worker-a still holds its 5 entries: nobody claimed them.", expected, got)
    return failed("The pending entries are not 5 entries owned by worker-b.", expected, got)


LESSON = Lesson(
    id="ch03",
    number=3,
    title="Key-value with Redis",
    database="Redis 8.2",
    summary="Data structures, TTL, eviction, idempotency keys, rate limits and streams with consumer groups.",
    guide=GuideRef(3, "3. Key-value with Redis"),
    consoles=("redis",),
    services=("redis",),
    make_up="make up-03",
    prepare=prepare_redis,
    prepare_note="Flushes logical database 5 and loads the lab's step 3.1 keys and step 3.8 stream; sets maxmemory-policy back to noeviction.",
    steps=(
        Step(
            id="structures",
            title="Data structures, mapped to SQL",
            guide=GuideRef(3, "Data structures, mapped to SQL"),
            prose=(
                "Every value lives under a **key** you choose, and you read it by that key: key naming is your schema (`ch03:borrower:B000001`).",
                'The console takes redis-cli syntax, one command per line, and prints replies the way redis-cli does: `"strings"`, `(integer) 42`, `(nil)`. Quote a key that contains a space.',
                "It works in logical database 5, so it does not disturb the lab (3), the checks (13) or the capstone (7).",
            ),
            examples=(
                Example("A string", "redis", "GET ch03:loan:L0000006:status"),
                Example(
                    "A counter",
                    "redis",
                    "INCR ch03:counter:applications_today\nGET ch03:counter:applications_today",
                ),
                Example(
                    "A hash is one row", "redis", "HGETALL ch03:borrower:B000001\nTYPE ch03:borrower:B000001"
                ),
                Example("A list as a queue", "redis", "LRANGE ch03:queue:documents_to_verify 0 -1"),
                Example("Count a score band", "redis", "ZCOUNT ch03:scores 600 700"),
            ),
            exercises=(
                Exercise(
                    id="ch03.top3",
                    number="3.1",
                    title="Top three scores",
                    console="redis",
                    task="`ch03:scores` is a sorted set of application ids scored by their credit score. Return the three highest, best first, with their scores.",
                    starter="ZRANGE ch03:scores 0 2",
                    hints=(
                        "ZRANGE returns lowest first; there is a reverse variant.",
                        "Add WITHSCORES to get the scores.",
                        "ZREVRANGE ch03:scores 0 2 WITHSCORES",
                    ),
                    solution="ZREVRANGE ch03:scores 0 2 WITHSCORES",
                    check=Match(ordered=True),
                    wrong=("ZRANGE ch03:scores 0 2 WITHSCORES", "ZREVRANGE ch03:scores 0 2"),
                    explain="A sorted set keeps members ordered by score: ORDER BY score DESC LIMIT 3 without sorting at read time.",
                ),
                Exercise(
                    id="ch03.sinter",
                    number="3.2",
                    title="Applications sharing a phone and a device",
                    console="redis",
                    task=(
                        "Two sets hold application ids: `ch03:phone:+999 7000:applications` (one phone) and `ch03:device:dev-1:applications` "
                        "(one device). Return the applications in both."
                    ),
                    starter="SMEMBERS ch03:device:dev-1:applications",
                    hints=(
                        "The SQL analogy is INTERSECT.",
                        "The first key contains a space: put it in double quotes.",
                        'SINTER "ch03:phone:+999 7000:applications" ch03:device:dev-1:applications',
                    ),
                    solution='SINTER "ch03:phone:+999 7000:applications" ch03:device:dev-1:applications',
                    check=Match(),
                    wrong=(
                        'SUNION "ch03:phone:+999 7000:applications" ch03:device:dev-1:applications',
                        "SINTER ch03:phone:+999 7000:applications ch03:device:dev-1:applications",
                    ),
                    explain="Without quotes, the key is split at the space into three arguments, and the intersection is empty.",
                ),
            ),
        ),
        Step(
            id="ttl",
            title="Time to live",
            guide=GuideRef(3, "Time to live"),
            prose=(
                "Any key can have a **TTL**; when it runs out the key is deleted. `TTL` returns the seconds left, `-1` for a key that never expires and `-2` for a key that does not exist.",
                "An expired key is never returned, even before Redis has physically removed it.",
            ),
            examples=(
                Example(
                    "A key that expires in 2 seconds",
                    "redis",
                    "SET ch03:session:abc cached-decision EX 2\nTTL ch03:session:abc\nTTL ch03:loan:L0000006:status",
                    note="Run it, wait two seconds, then run `GET ch03:session:abc`.",
                ),
            ),
            exercises=(
                Exercise(
                    id="ch03.ttl",
                    number="3.3",
                    title="A session that expires",
                    console="redis",
                    task="Store the value `cached-decision` under `ch03:session:me` so that it expires after 60 seconds, in one command.",
                    starter="SET ch03:session:me cached-decision",
                    hints=(
                        "SET takes options after the value.",
                        "EX sets the expiry in seconds.",
                        "SET ch03:session:me cached-decision EX 60",
                    ),
                    solution="SET ch03:session:me cached-decision EX 60",
                    check=Custom(check_session_ttl, setup="DEL ch03:session:me"),
                    wrong=(
                        "SET ch03:session:me cached-decision\nTTL ch03:session:me",
                        "SET ch03:session:me cached-decision EX 3600",
                    ),
                    explain="One command, so there is no moment when the key exists without its expiry.",
                ),
            ),
        ),
        Step(
            id="eviction",
            title="Eviction: what happens when memory runs out",
            guide=GuideRef(3, "Eviction: what happens when memory runs out"),
            prose=(
                "`maxmemory` limits Redis's memory and `maxmemory-policy` decides what happens at the limit. The image's defaults are `maxmemory 0` (no limit) and `noeviction` (reject writes when full).",
                "`allkeys-*` policies may evict any key, including pipeline state; `volatile-*` policies evict only keys that have a TTL. The lab watched `allkeys-lru` evict every key created in step 3.1.",
                "This console may change only `maxmemory`, `maxmemory-policy`, `appendonly` and `appendfsync` with `CONFIG SET`. Prepare sets the policy back to `noeviction`.",
                "A live demonstration: **Run the whole lab** above includes step 3.3, which fills memory under `allkeys-lru`. Eviction is server-wide, so it also evicts this lesson's keys in database 5. Press **Prepare data** afterwards.",
            ),
            examples=(
                Example("The memory settings", "redis", "CONFIG GET maxmemory*"),
                Example("Persistence defaults: RDB only", "redis", "CONFIG GET save\nCONFIG GET appendonly"),
            ),
            exercises=(
                Exercise(
                    id="ch03.eviction",
                    number="3.4",
                    title="Evict only what may go",
                    console="redis",
                    task=(
                        "This instance will hold cache entries, each with a TTL, next to keys without a TTL that must never be evicted. "
                        "Set the policy that evicts only keys with a TTL, least recently used first."
                    ),
                    starter="CONFIG GET maxmemory-policy",
                    hints=(
                        "CONFIG SET maxmemory-policy <policy>",
                        "The policies are noeviction, allkeys-lru, allkeys-lfu, allkeys-random, volatile-lru, volatile-lfu, volatile-random and volatile-ttl.",
                        "volatile- means only keys with an expiry; lru means least recently used.",
                    ),
                    solution="CONFIG SET maxmemory-policy volatile-lru",
                    check=Custom(check_volatile_lru, setup="CONFIG SET maxmemory-policy noeviction"),
                    wrong=(
                        "CONFIG SET maxmemory-policy allkeys-lru",
                        "CONFIG SET maxmemory-policy volatile-ttl",
                    ),
                    explain="The trap the guide names: dedup keys usually have a TTL too, so keep pipeline state on a noeviction instance.",
                ),
            ),
        ),
        Step(
            id="idempotency",
            title="Idempotency keys: processing each event once",
            guide=GuideRef(3, "Idempotency keys: processing each event once"),
            prose=(
                "Most message systems deliver **at least once**, so the same event can arrive twice. `SET dedup:<event_id> 1 NX EX <ttl>` sets the key only if it does not exist and says whether it did, in one atomic command.",
                "The lab replayed 300 of 2,000 payment events: without dedup the total was 152,790,584 cents, with dedup 133,237,006, the true total.",
            ),
            examples=(
                Example(
                    "NX: only if absent",
                    "redis",
                    "SET ch03:demo:nx first NX\nSET ch03:demo:nx second NX\nGET ch03:demo:nx",
                ),
            ),
            exercises=(
                Exercise(
                    id="ch03.dedup",
                    number="3.5",
                    title="Record an event once",
                    console="redis",
                    task=(
                        "Write the one command a worker runs before processing event `evt-42`: it records the key `ch03:dedup:evt-42` "
                        "only if it is not there yet, with an expiry of 7 days. The check runs it twice, like a duplicate delivery."
                    ),
                    starter="SET ch03:dedup:evt-42 1",
                    hints=(
                        "Two options on SET: one for 'only if it does not exist', one for the expiry.",
                        "7 days is 604800 seconds.",
                        "SET ch03:dedup:evt-42 1 NX EX 604800",
                    ),
                    solution="SET ch03:dedup:evt-42 1 NX EX 604800",
                    check=Custom(check_dedup, setup="DEL ch03:dedup:evt-42"),
                    wrong=("SET ch03:dedup:evt-42 1 EX 604800", "SETNX ch03:dedup:evt-42 1"),
                    explain="GET followed by SET would let two racing workers both see 'absent'; one atomic command cannot race.",
                ),
            ),
        ),
        Step(
            id="ratelimit",
            title="Rate limiting",
            guide=GuideRef(3, "Rate limiting"),
            prose=(
                "A **fixed-window counter**: `INCR rate:<client>:<window>`, with an expiry set on the first call. The lab allowed 10 calls a minute: of 25 calls from broker-17, 10 were allowed and 15 rejected.",
                "`MULTI` ... `EXEC` runs the commands in between as one transaction. Write all of it in one run: the console sends every line on the same connection.",
            ),
            examples=(
                Example(
                    "A transaction", "redis", "MULTI\nINCR ch03:demo:counter\nGET ch03:demo:counter\nEXEC"
                ),
            ),
            exercises=(
                Exercise(
                    id="ch03.ratelimit",
                    number="3.6",
                    title="Count a call in a fixed window",
                    console="redis",
                    task=(
                        "In one MULTI/EXEC transaction, count a call for broker-17 in `ch03:rate:broker-17:demo` and make the counter "
                        "expire after 60 seconds, setting the expiry only if the key has none yet. The check calls it twice."
                    ),
                    starter="MULTI\nINCR ch03:rate:broker-17:demo\nEXEC",
                    hints=(
                        "Add an EXPIRE between INCR and EXEC.",
                        "EXPIRE has an option that sets the expiry only when the key has none.",
                        "EXPIRE ch03:rate:broker-17:demo 60 NX",
                    ),
                    solution="MULTI\nINCR ch03:rate:broker-17:demo\nEXPIRE ch03:rate:broker-17:demo 60 NX\nEXEC",
                    check=Custom(check_rate_limit, setup="DEL ch03:rate:broker-17:demo"),
                    wrong=(
                        "MULTI\nINCR ch03:rate:broker-17:demo\nEXPIRE ch03:rate:broker-17:demo 60\nEXEC",
                        "INCR ch03:rate:broker-17:demo\nEXPIRE ch03:rate:broker-17:demo 60 NX",
                    ),
                    explain="A crash between INCR and EXPIRE cannot leave a counter that never expires, and NX keeps the window fixed.",
                ),
            ),
        ),
        Step(
            id="streams",
            title="Redis Streams with consumer groups",
            guide=GuideRef(3, "Redis Streams with consumer groups as a lightweight queue"),
            prose=(
                "A **stream** is an append-only log; a **consumer group** shares it between workers. `XREADGROUP ... >` delivers entries nobody in the group has received and records them as pending for that consumer, in the **pending entries list (PEL)**, until `XACK`.",
                "Redis never redelivers by itself. A dead worker's entries stay pending until another consumer claims them with `XAUTOCLAIM` (or `XCLAIM`).",
                "Prepare loaded the lab's stream `ch03:payments` (20 payments and one poison entry) with the group `loader`. Each check below recreates the group first.",
            ),
            examples=(
                Example("The first entries", "redis", "XRANGE ch03:payments - + COUNT 2\nXLEN ch03:payments"),
                Example("The group", "redis", "XINFO GROUPS ch03:payments\nXPENDING ch03:payments loader"),
                Example("Start the group again", "redis", RESET_GROUP),
            ),
            exercises=(
                Exercise(
                    id="ch03.readgroup",
                    number="3.7",
                    title="Read as a consumer in a group",
                    console="redis",
                    task="As consumer `worker-a` of the group `loader`, read 5 entries of `ch03:payments` that nobody in the group has received yet.",
                    starter="XREAD COUNT 5 STREAMS ch03:payments 0",
                    hints=(
                        "XREAD reads without a group; the group variant names the group and the consumer.",
                        "The special id > means 'never delivered to this group'.",
                        "XREADGROUP GROUP loader worker-a COUNT 5 STREAMS ch03:payments >",
                    ),
                    solution="XREADGROUP GROUP loader worker-a COUNT 5 STREAMS ch03:payments >",
                    check=Custom(check_readgroup, setup=RESET_GROUP),
                    wrong=(
                        "XREAD COUNT 5 STREAMS ch03:payments 0",
                        "XREADGROUP GROUP loader worker-a COUNT 5 STREAMS ch03:payments 0",
                    ),
                    explain="The 5 entries are now pending for worker-a: delivered, not acknowledged.",
                ),
                Exercise(
                    id="ch03.autoclaim",
                    number="3.8",
                    title="Claim a crashed worker's entries",
                    console="redis",
                    task=(
                        "The check makes worker-a read 5 entries and 'crash' before XACK. As `worker-b`, claim every pending entry of the group "
                        "`loader`, starting from the beginning of the PEL. Use a minimum idle time of 0 ms here (in production, something like 60000)."
                    ),
                    starter="XPENDING ch03:payments loader",
                    hints=(
                        "XAUTOCLAIM <stream> <group> <consumer> <min-idle-time> <start>",
                        "The start of the PEL is 0-0.",
                        "XAUTOCLAIM ch03:payments loader worker-b 0 0-0",
                    ),
                    solution="XAUTOCLAIM ch03:payments loader worker-b 0 0-0",
                    check=Custom(
                        check_autoclaim,
                        setup=RESET_GROUP
                        + "\nXREADGROUP GROUP loader worker-a COUNT 5 STREAMS ch03:payments >",
                    ),
                    wrong=(
                        "XREADGROUP GROUP loader worker-b COUNT 5 STREAMS ch03:payments >",
                        "XAUTOCLAIM ch03:payments loader worker-b 600000 0-0",
                    ),
                    explain="times_delivered went to 2 for each claimed entry: at-least-once delivery, so the consumer must be idempotent.",
                ),
            ),
        ),
    ),
)
