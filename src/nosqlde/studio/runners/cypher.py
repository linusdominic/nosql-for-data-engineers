"""The Neo4j console: Cypher through the neo4j driver, with PROFILE and EXPLAIN summarised.

Statements are separated by `;`. Each one runs in its own auto-commit transaction (so
`CALL { ... } IN TRANSACTIONS` works). After a statement that creates an index or a
constraint, the console waits for the index to come online, so a PROFILE straight after
it already uses the index.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Iterator
from typing import Any

from nosqlde.config import SETTINGS
from nosqlde.studio.runners.base import Block, RunResult, ServiceDown, StudioError, error_block
from nosqlde.studio.runners.cql import split_statements

TIMEOUT_S = 20.0


def _walk(plan: Any, depth: int = 0) -> Iterator[tuple[int, Any]]:
    yield depth, plan
    for child in plan.get("children", []) or []:
        yield from _walk(child, depth + 1)


def plan_summary(plan: dict[str, Any], profiled: bool) -> dict[str, Any]:
    """Operators (root first), db hits and rows, like chapter 6's PROFILE table."""
    operators = []
    total_hits = 0
    for depth, node in _walk(plan):
        op = str(node.get("operatorType", "?")).split("@")[0]
        args = node.get("args", {}) or {}
        hits = int(node.get("dbHits", 0) or 0)
        total_hits += hits
        operators.append(
            {
                "depth": depth,
                "operator": op,
                "details": args.get("Details", ""),
                "rows": node.get("rows") if profiled else args.get("EstimatedRows"),
                "dbHits": hits if profiled else None,
            }
        )
    return {
        "operators": " <- ".join(o["operator"] for o in operators),
        "total_db_hits": total_hits if profiled else None,
        "rows": operators[0]["rows"] if operators else None,
        "tree": operators,
    }


def to_plain(value: Any) -> Any:
    """Driver values to JSON-friendly Python: nodes, relationships and paths included."""
    from neo4j.graph import Node, Path, Relationship

    if isinstance(value, Node):
        return {"_labels": sorted(value.labels), **{k: to_plain(v) for k, v in value.items()}}
    if isinstance(value, Relationship):
        return {"_type": value.type, **{k: to_plain(v) for k, v in value.items()}}
    if isinstance(value, Path):
        return {
            "_path": " ".join(_path_text(value)),
            "length": len(value.relationships),
            "nodes": [to_plain(n) for n in value.nodes],
        }
    if isinstance(value, list):
        return [to_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: to_plain(v) for k, v in value.items()}
    if hasattr(value, "iso_format"):
        return value.iso_format()
    return value


def _node_label(node: Any) -> str:
    labels = ":".join(sorted(node.labels))
    key = next(
        (
            node[k]
            for k in ("application_id", "borrower_id", "number", "device_id", "key", "name")
            if k in node
        ),
        None,
    )
    return f"(:{labels} {key!r})" if key is not None else f"(:{labels})"


def _path_text(path: Any) -> list[str]:
    parts = [_node_label(path.nodes[0])]
    for i, rel in enumerate(path.relationships):
        forward = rel.start_node is not None and rel.start_node.element_id == path.nodes[i].element_id
        parts.append(f"-[:{rel.type}]->" if forward else f"<-[:{rel.type}]-")
        parts.append(_node_label(path.nodes[i + 1]))
    return parts


class CypherRunner:
    console = "cypher"

    def __init__(self) -> None:
        self._driver: Any = None
        self._lock = threading.Lock()

    def driver(self) -> Any:
        with self._lock:
            if self._driver is None:
                from neo4j import GraphDatabase

                self._driver = GraphDatabase.driver(
                    SETTINGS.neo4j_uri,
                    auth=(SETTINGS.neo4j_user, SETTINGS.neo4j_password),
                    connection_timeout=3,
                    max_transaction_retry_time=2,
                )
            return self._driver

    def close(self) -> None:
        with self._lock:
            if self._driver is not None:
                self._driver.close()
                self._driver = None

    def run(self, text: str, max_rows: int = 200) -> RunResult:
        result = RunResult(self.console)
        start = time.perf_counter()
        statements = split_statements(text, line_comments=("//",), quotes="'\"`")
        if not statements:
            result.blocks.append(Block(command="", kind="text", text="(nothing to run)"))
            return result
        for stmt in statements:
            t0 = time.perf_counter()
            try:
                block = self._execute(stmt, max_rows)
            except StudioError as err:
                block = error_block(stmt, err)
            except Exception as err:
                block = self._error(stmt, err)
            if not block.elapsed_ms:
                block.elapsed_ms = (time.perf_counter() - t0) * 1000
            result.blocks.append(block)
            if block.is_error:
                break
        result.elapsed_ms = (time.perf_counter() - start) * 1000
        return result

    def _error(self, stmt: str, err: Exception) -> Block:
        from neo4j.exceptions import Neo4jError, ServiceUnavailable

        if isinstance(err, (ServiceUnavailable, OSError)):
            return error_block(
                stmt,
                ServiceDown(
                    f"Neo4j is not reachable at {SETTINGS.neo4j_uri} ({type(err).__name__}).",
                    title="Neo4j is down",
                    hint="Start it with `make up-06` (or `make up-capstone`).",
                ),
            )
        if isinstance(err, Neo4jError):
            message = " ".join((err.message or str(err)).split())
            block = error_block(stmt, StudioError(message, title=err.code or "Neo4jError"))
            block.data = {"code": err.code, "message": message}
            return block
        return error_block(stmt, err)

    def _execute(self, stmt: str, max_rows: int) -> Block:
        from neo4j import Query

        driver = self.driver()
        t0 = time.perf_counter()
        with driver.session(database="neo4j") as session:
            res = session.run(Query(stmt, timeout=TIMEOUT_S))
            keys = list(res.keys())
            rows: list[list[Any]] = []
            truncated = False
            for record in res:
                if len(rows) >= max_rows:
                    truncated = True
                    break
                rows.append([to_plain(v) for v in record.values()])
            summary = res.consume()
        elapsed = (time.perf_counter() - t0) * 1000
        records = [dict(zip(keys, r, strict=True)) for r in rows]
        notes: list[str] = []
        profile = summary.profile
        plan = summary.plan
        if profile or plan:
            ps = plan_summary(profile or plan, profiled=bool(profile))
            table_rows = [
                [("  " * o["depth"]) + o["operator"], o["details"], o["rows"], o["dbHits"]]
                for o in ps["tree"]
            ]
            block = Block(
                command=stmt,
                kind="plan",
                columns=["operator", "details", "rows" if profile else "estimated rows", "db hits"],
                rows=table_rows,
                value={"result": records[:50], "plan": ps},
                data={"records": records, "plan": ps, "profiled": bool(profile)},
            )
            block.notes.append(f"operators: {ps['operators']}")
            if profile:
                block.notes.append(f"total db hits: {ps['total_db_hits']}; rows: {ps['rows']}")
        elif keys:
            block = Block(
                command=stmt, kind="table", columns=keys, rows=rows, truncated=truncated, data=records
            )
            notes.append(f"{len(rows)}{'+' if truncated else ''} record{'s' if len(rows) != 1 else ''}")
        else:
            block = Block(command=stmt, kind="text", text="OK", data=[])
        counters = summary.counters
        changed = {
            k: v for k, v in vars(counters).items() if isinstance(v, int) and not isinstance(v, bool) and v
        }
        if changed:
            notes.append(", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in sorted(changed.items())))
        for status in summary.gql_status_objects:
            if status.is_notification:
                notes.append(f"{status.severity.name}: {status.status_description}")
        if re.match(
            r"^\s*CREATE\s+(INDEX|CONSTRAINT|RANGE\s+INDEX|TEXT\s+INDEX|POINT\s+INDEX)", stmt, re.IGNORECASE
        ):
            driver.execute_query("CALL db.awaitIndexes(30)")
            notes.append("waited for the new index to come online (db.awaitIndexes)")
        block.notes.extend(notes)
        block.elapsed_ms = elapsed
        return block
