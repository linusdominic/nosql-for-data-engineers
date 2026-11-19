"""Check chapter 6's exercises against Neo4j (reloads the lab graph first)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb

from nosqlde import checks, clients, datagen, graph
from nosqlde.labs.ch06_neo4j import identity_rows, load, reset


def run(solutions: bool = False) -> int:
    checker, answers = checks.start("Chapter 6 (Neo4j)", "ch06_neo4j.py", solutions)
    driver = clients.neo4j()
    world = datagen.generate(seed=42)
    rows = identity_rows(world)
    reset(driver)
    load(driver, rows)

    def ex1() -> str:
        got = [tuple(r.values()) for r in driver.execute_query(answers.shared_device_query()).records]
        by_device: dict[str, list[dict[str, str]]] = {}
        for r in rows:
            by_device.setdefault(r["device_id"], []).append(r)
        want = sorted(
            (a["application_id"], b["application_id"], dev)
            for dev, apps in by_device.items()
            for a in apps
            for b in apps
            if a["application_id"] < b["application_id"] and a["borrower_id"] != b["borrower_id"]
        )
        assert got == want, (
            f"expected {len(want)} pairs (first: {want[:2]}), got {len(got)} (first: {got[:2]})"
        )
        return f"{len(got)} pairs of applications by different people sharing a device"

    def ex2() -> str:
        ring = world.rings[0]
        got = answers.connected_applications(driver, ring[0], 10)
        assert set(ring) <= set(got), f"the planted ring {ring} should be reachable, got {got}"
        assert got == sorted(got), "return the ids sorted"
        one = answers.connected_applications(driver, ring[0], 2)
        assert len(one) < len(got), (
            "max_hops must limit the traversal (2 hops should reach fewer applications)"
        )
        lonely = next(
            r["application_id"]
            for r in rows
            if r["application_id"] not in {a for x in world.rings for a in x}
        )
        assert lonely in answers.connected_applications(driver, lonely, 4), "include the starting application"
        return f"{len(got)} applications within 10 hops of {ring[0]}, {len(one)} within 2"

    def ex3() -> str:
        pairs = [
            (r["application_id"], f"{kind}:{r[kind]}")
            for r in rows
            for kind in ("phone", "device_id", "address_key")
        ]
        got = answers.group_by_shared_identifiers(pairs)
        want = sorted(graph.components_from_shared_keys(pairs).values())
        assert got == want, (
            f"expected {len(want)} groups (largest {max(len(g) for g in want)}), "
            f"got {len(got)} (largest {max((len(g) for g in got), default=0)})"
        )
        assert answers.group_by_shared_identifiers(
            [("x", "k1"), ("y", "k1"), ("y", "k2"), ("z", "k2"), ("q", "k3")]
        ) == [["q"], ["x", "y", "z"]], "x-y share k1 and y-z share k2, so x, y, z are one group; q is alone"
        return f"{len(got)} groups, matches the reference union-find"

    def ex4() -> str:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "edges.parquet"
            n = answers.export_edges(driver, path)
            assert path.exists(), f"{path} was not written"
            count, kinds = duckdb.connect().execute(
                f"SELECT count(*), list(DISTINCT kind ORDER BY kind) FROM '{path}'"
            ).fetchone() or (0, [])
            cols = [c[0] for c in duckdb.connect().execute(f"DESCRIBE SELECT * FROM '{path}'").fetchall()]
        want = len(rows) * 3
        assert cols == ["application_id", "kind", "value"], (
            f"columns should be application_id, kind, value; got {cols}"
        )
        assert n == count == want, f"expected {want} rows (3 per application); returned {n}, file has {count}"
        assert kinds == ["AT_ADDRESS", "USES_DEVICE", "USES_PHONE"], f"unexpected kinds {kinds}"
        return f"{count} edge rows written to Parquet"

    checker.run("6.1 shared_device_query", ex1)
    checker.run("6.2 connected_applications", ex2)
    checker.run("6.3 group_by_shared_identifiers", ex3)
    checker.run("6.4 export_edges", ex4)
    driver.close()
    return checker.finish()
