"""Connected components with union-find, for graph results exported to tables.

Neo4j Community does not ship graph algorithms (the Graph Data Science library is a
separate plugin). Once the edges are in a table, connected components are a few lines
of Python, and that is often how a data engineer ends up computing them anyway.
"""

from __future__ import annotations

from collections.abc import Iterable


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:  # path compression
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # Deterministic: the smaller id becomes the root, so component ids are stable.
            if rb < ra:
                ra, rb = rb, ra
            self.parent[rb] = ra


def connected_components(edges: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Map every node to a component id (the smallest node id in its component)."""
    uf = UnionFind()
    for a, b in edges:
        uf.union(a, b)
    return {node: uf.find(node) for node in uf.parent}


def components_from_shared_keys(pairs: Iterable[tuple[str, str]]) -> dict[str, list[str]]:
    """Group entities that share any key, directly or through others.

    `pairs` are (entity, key) rows, for example (application_id, "phone:+999 7..."),
    which is exactly the shape of an edge table exported from a graph. Returns
    {component_id: sorted entity ids}, including singletons.
    """
    uf = UnionFind()
    entities: set[str] = set()
    for entity, key in pairs:
        entities.add(entity)
        uf.union(f"e:{entity}", f"k:{key}")
    groups: dict[str, list[str]] = {}
    for entity in entities:
        groups.setdefault(uf.find(f"e:{entity}"), []).append(entity)
    return {min(members): sorted(members) for members in groups.values()}
