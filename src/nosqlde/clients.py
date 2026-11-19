"""Connect to each database, with an error message that says what to start.

Every lab and check goes through these helpers, so a reader who forgot `make up-NN`
gets one clear line instead of a driver stack trace.
"""

from __future__ import annotations

import logging
from typing import Any

import redis
from neo4j import Driver, GraphDatabase
from pymongo import MongoClient

from nosqlde.config import SETTINGS


class ServiceUnavailable(RuntimeError):
    """Raised when a database container is not reachable."""


def _unavailable(service: str, target: str, chapter: str, err: Exception) -> ServiceUnavailable:
    return ServiceUnavailable(
        f"{service} is not reachable at {target} ({type(err).__name__}: {err}).\n"
        f"Start it with `make up-{chapter}` (or `make up-capstone`) and try again. "
        "See README > Troubleshooting if it does not become healthy."
    )


def mongo(timeout_ms: int = 3000) -> MongoClient[dict[str, Any]]:
    """A MongoClient for the single-node replica set."""
    client: MongoClient[dict[str, Any]] = MongoClient(
        SETTINGS.mongo_uri, serverSelectionTimeoutMS=timeout_ms, tz_aware=True
    )
    try:
        client.admin.command("ping")
    except Exception as err:
        client.close()
        raise _unavailable("MongoDB", SETTINGS.mongo_uri, "02", err) from err
    return client


def redis_client(db: int | None = None) -> redis.Redis:
    """A Redis client that returns str instead of bytes. `db` picks a logical database."""
    client = redis.Redis.from_url(SETTINGS.redis_url, decode_responses=True, socket_timeout=5, db=db or 0)
    try:
        client.ping()
    except Exception as err:
        raise _unavailable("Redis", SETTINGS.redis_url, "03", err) from err
    return client


def cassandra(keyspace: str | None = None) -> Any:
    """A cassandra-driver Session. The caller shuts down `session.cluster` when done."""
    # imported lazily: cassandra-driver is slow to import
    from cassandra.cluster import EXEC_PROFILE_DEFAULT, Cluster, ExecutionProfile
    from cassandra.policies import RoundRobinPolicy

    # The driver logs a warning per connection about the protocol version it negotiated
    # and about the missing local DC; neither matters for a single local node.
    logging.getLogger("cassandra").setLevel(logging.ERROR)
    cluster = Cluster(
        [SETTINGS.cassandra_host],
        port=SETTINGS.cassandra_port,
        execution_profiles={EXEC_PROFILE_DEFAULT: ExecutionProfile(load_balancing_policy=RoundRobinPolicy())},
        connect_timeout=10,
    )
    try:
        session = cluster.connect(keyspace)
    except Exception as err:
        cluster.shutdown()
        target = f"{SETTINGS.cassandra_host}:{SETTINGS.cassandra_port}"
        raise _unavailable("Cassandra", target, "04", err) from err
    return session


def dynamodb_client() -> Any:
    """A boto3 DynamoDB client pointed at DynamoDB Local."""
    import boto3

    client = boto3.client(
        "dynamodb",
        endpoint_url=SETTINGS.dynamodb_endpoint,
        region_name="us-east-1",
        # DynamoDB Local accepts any key made of letters and digits. These are not secrets.
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )
    try:
        client.list_tables(Limit=1)
    except Exception as err:
        raise _unavailable("DynamoDB Local", SETTINGS.dynamodb_endpoint, "05", err) from err
    return client


def dynamodb_resource() -> Any:
    """A boto3 DynamoDB resource (the higher-level API with Table objects)."""
    import boto3

    dynamodb_client()  # fail early with a clear message if DynamoDB Local is down
    return boto3.resource(
        "dynamodb",
        endpoint_url=SETTINGS.dynamodb_endpoint,
        region_name="us-east-1",
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )


def dynamodb_streams_client() -> Any:
    """A boto3 DynamoDB Streams client pointed at DynamoDB Local."""
    import boto3

    return boto3.client(
        "dynamodbstreams",
        endpoint_url=SETTINGS.dynamodb_endpoint,
        region_name="us-east-1",
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )


def neo4j() -> Driver:
    """A Neo4j driver. Close it when done (it is a context manager)."""
    driver = GraphDatabase.driver(SETTINGS.neo4j_uri, auth=(SETTINGS.neo4j_user, SETTINGS.neo4j_password))
    try:
        driver.verify_connectivity()
    except Exception as err:
        driver.close()
        raise _unavailable("Neo4j", SETTINGS.neo4j_uri, "06", err) from err
    return driver
