"""Check chapter 2's exercises against MongoDB (database `larkspur_ch02_check`)."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from nosqlde import checks, clients, datagen

DB = "larkspur_ch02_check"


def run(solutions: bool = False) -> int:
    checker, answers = checks.start("Chapter 2 (MongoDB)", "ch02_mongodb.py", solutions)
    client = clients.mongo()
    client.drop_database(DB)
    db = client[DB]
    world = datagen.generate(seed=42)
    docs = datagen.applications_as_of(world, world.as_of)
    db.applications.insert_many(docs)

    def ex1() -> str:
        sample = db.applications.find_one({"_id": "A0000006"})
        assert sample is not None
        rows = answers.explode_documents(sample)
        assert isinstance(rows, list), f"expected a list, got {type(rows).__name__}"
        assert len(rows) == len(sample["documents"]), (
            f"A0000006 has {len(sample['documents'])} documents, you returned {len(rows)} rows"
        )
        want_keys = {"application_id", "position", "doc_type", "uploaded_at", "verified"}
        assert set(rows[0]) == want_keys, f"row keys should be {sorted(want_keys)}, got {sorted(rows[0])}"
        assert [r["position"] for r in rows] == list(range(len(rows))), "positions must be 0, 1, 2..."
        assert answers.explode_documents({"application_id": "X"}) == [], (
            "a document without a `documents` field must give []"
        )
        assert answers.explode_documents({"application_id": "X", "documents": []}) == []
        total = sum(len(answers.explode_documents(d)) for d in db.applications.find())
        expected = sum(len(d["documents"]) for d in docs)
        assert total == expected, f"all applications: expected {expected} rows, got {total}"
        return f"{total} document rows from {len(docs)} applications"

    def ex2() -> str:
        pipeline = answers.approval_rate_pipeline()
        got = list(db.applications.aggregate(pipeline))
        decided: Counter[str] = Counter()
        approved: Counter[str] = Counter()
        for d in docs:
            if d["status"] == "submitted":
                continue
            decided[d["channel"]] += 1
            approved[d["channel"]] += d["status"] in ("approved", "funded")
        want = [
            {
                "_id": c,
                "decided": decided[c],
                "approved": approved[c],
                "approval_rate": round(approved[c] / decided[c], 4),
            }
            for c in sorted(decided)
        ]
        simplified = [{k: g.get(k) for k in ("_id", "decided", "approved", "approval_rate")} for g in got]
        assert [g["_id"] for g in simplified] == [w["_id"] for w in want], (
            f"expected one row per channel in order {[w['_id'] for w in want]}, "
            f"got {[g['_id'] for g in simplified]}"
        )
        for g, w in zip(simplified, want, strict=True):
            assert g == w, f"channel {w['_id']}: expected {w}, got {g}"
        return ", ".join(f"{w['_id']}={w['approval_rate']}" for w in want)

    def ex3() -> str:
        coll = db.extract
        coll.drop()
        t1 = datetime(2025, 3, 31, 23, 59, 59, tzinfo=UTC)
        coll.insert_many(datagen.applications_as_of(world, t1))
        n1 = coll.count_documents({})
        rows, wm1 = answers.extract_since(coll, None)
        assert len(rows) == n1, f"first run (watermark None) should return all {n1}, got {len(rows)}"
        assert wm1 == max(d["updated_at"] for d in rows), "watermark should be the max updated_at"
        keys = [(d["updated_at"], d["_id"]) for d in rows]
        assert keys == sorted(keys), "documents must be sorted by updated_at, then _id"
        bump = wm1 + timedelta(seconds=1)
        coll.update_many({"_id": {"$in": ["A0000001", "A0000002"]}}, {"$set": {"updated_at": bump}})
        coll.insert_one({"_id": "NEW1", "updated_at": bump})
        rows2, wm2 = answers.extract_since(coll, wm1)
        assert sorted(d["_id"] for d in rows2) == ["A0000001", "A0000002", "NEW1"], (
            f"second run should return the 3 changed documents, got {[d['_id'] for d in rows2]}"
        )
        assert wm2 == bump, f"watermark should move to {bump}, got {wm2}"
        rows3, wm3 = answers.extract_since(coll, wm2)
        assert rows3 == [], f"with no changes, expected [], got {len(rows3)} documents"
        assert wm3 == wm2, "with no changes the watermark must stay where it was"
        return f"full {n1}, incremental 3, then 0; watermark never moved backwards"

    def ex4() -> str:
        coll = db.cdc
        coll.drop()
        coll.insert_one({"_id": "seed"})
        with coll.watch() as stream:
            stream.try_next()
            token: dict[str, Any] = stream.resume_token  # type: ignore[assignment]
        coll.insert_one({"_id": "c1"})
        coll.update_one({"_id": "c1"}, {"$set": {"x": 1}})
        coll.insert_one({"_id": "c2"})
        coll.delete_one({"_id": "c1"})
        got = answers.read_changes_after(coll, token, 4)
        want = [("insert", "c1"), ("update", "c1"), ("insert", "c2"), ("delete", "c1")]
        assert [tuple(g) for g in got] == want, f"expected {want}, got {got}"
        return "resumed and received insert, update, insert, delete in order"

    checker.run("2.1 explode_documents", ex1)
    checker.run("2.2 approval_rate_pipeline", ex2)
    checker.run("2.3 extract_since", ex3)
    checker.run("2.4 read_changes_after", ex4)
    client.drop_database(DB)
    client.close()
    return checker.finish()
