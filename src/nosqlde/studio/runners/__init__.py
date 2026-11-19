"""One console per database. Each runner turns console text into a RunResult."""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from nosqlde.config import SETTINGS
from nosqlde.studio.runners.base import Block, RunResult, StudioError, error_block
from nosqlde.studio.runners.cql import CqlRunner, CqlState
from nosqlde.studio.runners.cypher import CypherRunner
from nosqlde.studio.runners.duck import DuckRunner
from nosqlde.studio.runners.dynamo import DynamoRunner
from nosqlde.studio.runners.mongo import MongoRunner
from nosqlde.studio.runners.redis_cli import RedisRunner


@dataclass(frozen=True)
class ConsoleInfo:
    id: str
    label: str
    language: str
    service: str  # status key
    placeholder: str


CONSOLES: dict[str, ConsoleInfo] = {
    "mongo": ConsoleInfo("mongo", "MongoDB", "mongosh (subset)", "mongo", "db.applications.findOne()"),
    "redis": ConsoleInfo("redis", "Redis", "redis-cli", "redis", "PING"),
    "cql": ConsoleInfo("cql", "Cassandra", "CQL", "cassandra", "SELECT * FROM payments_by_loan LIMIT 3;"),
    "dynamodb": ConsoleInfo(
        "dynamodb",
        "DynamoDB",
        "PartiQL or JSON",
        "dynamodb",
        "SELECT * FROM larkspur_studio WHERE PK = 'BORROWER#B000001'",
    ),
    "cypher": ConsoleInfo(
        "cypher", "Neo4j", "Cypher", "neo4j", "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n"
    ),
    "duckdb": ConsoleInfo("duckdb", "DuckDB", "SQL", "duckdb", "SELECT 42 AS answer"),
}


@dataclass(frozen=True)
class Service:
    id: str
    label: str
    host: str
    port: int
    make: str


def _host_port(url: str, default_port: int) -> tuple[str, int]:
    parsed = urlparse(url)
    return parsed.hostname or "localhost", parsed.port or default_port


def services() -> list[Service]:
    mh, mp = _host_port(SETTINGS.mongo_uri, 27017)
    rh, rp = _host_port(SETTINGS.redis_url, 6379)
    dh, dp = _host_port(SETTINGS.dynamodb_endpoint, 8000)
    nh, np_ = _host_port(SETTINGS.neo4j_uri, 7687)
    return [
        Service("mongo", "MongoDB", mh, mp, "make up-02"),
        Service("redis", "Redis", rh, rp, "make up-03"),
        Service("cassandra", "Cassandra", SETTINGS.cassandra_host, SETTINGS.cassandra_port, "make up-04"),
        Service("dynamodb", "DynamoDB Local", dh, dp, "make up-05"),
        Service("neo4j", "Neo4j", nh, np_, "make up-06"),
    ]


def port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class Consoles:
    """Holds one runner per console, created lazily and reused across requests."""

    def __init__(self) -> None:
        self.mongo = MongoRunner()
        self.redis = RedisRunner()
        self.cql = CqlRunner()
        self.dynamodb = DynamoRunner()
        self.cypher = CypherRunner()
        self.duckdb = DuckRunner()
        self._status: tuple[float, list[dict[str, Any]]] | None = None
        self._status_lock = threading.Lock()

    def run(self, console: str, text: str, max_rows: int = 200, *, isolated: bool = False) -> RunResult:
        """Run console text. `isolated=True` (checks) ignores console session state:
        cqlsh settings start from the defaults and DuckDB uses a fresh connection."""
        if console == "mongo":
            return self.mongo.run(text, max_rows)
        if console == "redis":
            return self.redis.run(text, max_rows)
        if console == "cql":
            return self.cql.run(text, max_rows, state=CqlState() if isolated else None)
        if console == "dynamodb":
            return self.dynamodb.run(text, max_rows)
        if console == "cypher":
            return self.cypher.run(text, max_rows)
        if console == "duckdb":
            return self.duckdb.run(text, max_rows, fresh=isolated)
        result = RunResult(console)
        result.blocks.append(error_block("", StudioError(f"unknown console {console!r}")))
        return result

    def status(self, max_age: float = 3.0) -> list[dict[str, Any]]:
        with self._status_lock:
            now = time.monotonic()
            if self._status and now - self._status[0] < max_age:
                return self._status[1]
            out = [
                {
                    "id": s.id,
                    "label": s.label,
                    "up": port_open(s.host, s.port),
                    "make": s.make,
                    "port": s.port,
                }
                for s in services()
            ]
            lake = SETTINGS.lake_dir / "capstone" / "marts" / "fct_loan.parquet"
            out.append(
                {
                    "id": "duckdb",
                    "label": "DuckDB",
                    "up": True,
                    "make": "make capstone",
                    "port": None,
                    "detail": "capstone lake present" if lake.exists() else "no capstone lake yet",
                }
            )
            self._status = (now, out)
            return out

    def close(self) -> None:
        for runner in (self.mongo, self.redis, self.cql, self.dynamodb, self.cypher, self.duckdb):
            with contextlib.suppress(Exception):
                runner.close()


__all__ = ["CONSOLES", "Block", "ConsoleInfo", "Consoles", "RunResult", "StudioError"]
