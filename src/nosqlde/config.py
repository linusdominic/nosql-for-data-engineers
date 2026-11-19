"""Connection settings for the local databases.

Every value can be overridden with an environment variable, so a reader whose port is
already taken can change docker-compose.yml and export the matching variable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    """Where each database listens. Defaults match docker-compose.yml."""

    # directConnection=true: talk to this one node and do not follow the replica-set
    # member address ("localhost:27017" inside the container) that the server advertises.
    mongo_uri: str = _env("NOSQLDE_MONGO_URI", "mongodb://localhost:27117/?directConnection=true")
    redis_url: str = _env("NOSQLDE_REDIS_URL", "redis://localhost:6479")
    cassandra_host: str = _env("NOSQLDE_CASSANDRA_HOST", "127.0.0.1")
    cassandra_port: int = int(_env("NOSQLDE_CASSANDRA_PORT", "9142"))
    dynamodb_endpoint: str = _env("NOSQLDE_DYNAMODB_ENDPOINT", "http://localhost:8100")
    neo4j_uri: str = _env("NOSQLDE_NEO4J_URI", "bolt://localhost:7787")
    neo4j_user: str = _env("NOSQLDE_NEO4J_USER", "neo4j")
    # Local-only password for a throwaway container, set in docker-compose.yml.
    neo4j_password: str = _env("NOSQLDE_NEO4J_PASSWORD", "nosqlde-local-only")
    lake_dir: Path = Path(_env("NOSQLDE_LAKE_DIR", "lake"))


SETTINGS = Settings()
