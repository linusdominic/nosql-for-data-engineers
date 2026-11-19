# 6. Graph with Neo4j

Time: about 1.5 hours (30 minutes reading, 15 minutes lab, 45 minutes exercises).

```bash
make up-06      # Neo4j 5.26.33 Community on localhost:7787 (Bolt) and :7574 (browser)
make lab-06
make check-06
make down
```

Statements in this chapter apply to Neo4j 5.26 Community Edition
(`neo4j:5.26.33-community`, a long-term-support release) and the Python driver 6.4.1.

## The model

A graph database stores **nodes** (things) and **relationships** (connections between
two nodes). Both can have **properties** (key-value pairs). Nodes have zero or more
**labels** (in practice, at least one), which play the part of table names; relationships have exactly one **type**
and a direction.

```text
(:Person {borrower_id})-[:SUBMITTED]->(:Application {application_id, status, product})
(:Application)-[:USES_PHONE]->(:Phone {number})
(:Application)-[:USES_DEVICE]->(:Device {device_id})
(:Application)-[:AT_ADDRESS]->(:Address {key})
```

| Relational | Neo4j |
|---|---|
| a row in an entity table | a node with a label |
| a foreign key or a row in a join table | a relationship, stored as a pointer between two nodes |
| a join, computed at query time | following stored relationships |
| `SELECT ... FROM ... JOIN ...` | `MATCH (a)-[:REL]->(b) RETURN ...` (Cypher) |
| recursive CTE | variable-length pattern `-[:REL*1..6]-` |

The point of storing relationships is that following one costs the same however big the
graph is: the database jumps from a node to its neighbours directly, instead of looking
them up in an index of the whole join table. That makes questions that are many joins
deep ("everything connected to this application within six hops") practical.

## Constraints, and Community versus Enterprise

Step 6.1 of `make lab-06` creates uniqueness constraints, which Community supports and
which create an index behind the scenes, then tries a property existence constraint:

```text
created 5 uniqueness constraints (each one is backed by an index)
property existence constraint -> Neo.DatabaseError.Schema.ConstraintCreationFailed: ...requires Neo4j Enterprise Edition. Note that only the first found violation is shown.
```

In Neo4j 5, these are Enterprise-only: property existence, property type and node/
relationship key constraints; more than one user database; role-based access control;
clustering; online backup. The Graph Data Science library (graph algorithms) is a
separate plugin in both editions. Everything in this chapter runs on Community.

## Loading: `UNWIND` plus `MERGE`

`MERGE` means "match this pattern, or create it if it does not exist". It is how you
make a load re-runnable: running it twice does not duplicate nodes. `UNWIND $rows`
turns a list parameter into rows, so one round trip loads a batch. The load query
(`LOAD` in `src/nosqlde/labs/ch06_neo4j.py`), abridged:

```cypher
UNWIND $rows AS r
MERGE (p:Person {borrower_id: r.borrower_id}) ON CREATE SET p.name = r.name
MERGE (a:Application {application_id: r.application_id})
  SET a.status = r.status, a.product = r.product
MERGE (p)-[:SUBMITTED]->(a)
MERGE (ph:Phone {number: r.phone})
MERGE (a)-[:USES_PHONE]->(ph)
...
```

Always create the uniqueness constraint before a `MERGE` load: without an index, each
`MERGE` scans every node with that label, and concurrent loads can create duplicates.
Step 6.2:

```text
loaded 2393 applications in 0.2s (batches of 500)
node label   count
-----------  -----
Address      1940
Application  2393
Device       1998
Person       2000
Phone        1993
relationship type  count
-----------------  -----
AT_ADDRESS         2393
SUBMITTED          2393
USES_DEVICE        2393
USES_PHONE         2393
```

Fewer phones (1,993) than applications (2,393) is the interesting part: some
applications share a phone.

## Cypher patterns versus SQL joins

"Pairs of applications by different people that share a phone." In Cypher you draw the
pattern; in SQL you self-join an edge table. Step 6.3 runs both and compares:

```cypher
MATCH (p1:Person)-[:SUBMITTED]->(a1:Application)-[:USES_PHONE]->(ph:Phone)
      <-[:USES_PHONE]-(a2:Application)<-[:SUBMITTED]-(p2:Person)
WHERE a1.application_id < a2.application_id AND p1 <> p2
RETURN a1.application_id AS a1, a2.application_id AS a2, ph.number AS phone
```

```sql
SELECT e1.application_id AS a1, e2.application_id AS a2, e1.value AS phone
FROM edges e1 JOIN edges e2
  ON e1.kind = 'USES_PHONE' AND e2.kind = 'USES_PHONE' AND e1.value = e2.value
 AND e1.application_id < e2.application_id AND e1.borrower_id <> e2.borrower_id
```

```text
Cypher: 11 pairs of applications by different people sharing a phone
SQL self-join over the exported edge table: 11 pairs; identical: True
a1        a2        phone
--------  --------  --------------
A0000030  A0001199  +999 767170804
A0000193  A0002033  +999 759988134
A0000305  A0001458  +999 715160660
```

For one hop the two are equally easy. The difference appears with depth.

## A lending use case: fraud rings

A **fraud ring** is a group of applications by apparently different people who share
identifiers: one person (or one gang) behind several identities. The generator plants 8
rings, chained so that no single identifier links a whole ring: member 1 shares a phone
with member 2, who shares a device with member 3, who shares an address with member 4.
Only a multi-hop traversal finds them.

Step 6.4 starts from one ring member and follows any shared identifier up to ten hops:

```cypher
MATCH (start:Application {application_id: $id})
      -[:USES_PHONE|USES_DEVICE|AT_ADDRESS*1..10]-(other:Application)
RETURN DISTINCT other.application_id AS id
```

```text
applications reachable from A0000030 through shared phones, devices or addresses: ['A0000030', 'A0000185', 'A0000302', 'A0000413', 'A0001199', 'A0001493', 'A0001525', 'A0002134']
planted ring (ground truth from the generator): ['A0000030', 'A0000302', 'A0000413', 'A0001199', 'A0001525']
the same question as a recursive CTE in DuckDB: ['A0000030', 'A0000185', 'A0000302', 'A0000413', 'A0001199', 'A0001493', 'A0001525', 'A0002134']
  A0000185 is not in the planted ring: borrower B001204 also submitted a ring application
  A0001493 is not in the planted ring: borrower B001037 is linked through a ring member
  A0002134 is not in the planted ring: borrower B001829 also submitted a ring application
```

The traversal found the ring and three more applications, and the lab explains each:
two are second applications by ring borrowers (they reuse their own phone or device),
one belongs to a person linked to a ring member by an address. This is the real-world
shape of the problem: links propagate to innocent neighbours, so a graph result is a
list of cases to investigate, not a verdict.

The recursive CTE gives the same answer. It works, but it rejoins the edge table at every
level and you have to think about cycles; the Cypher version is the pattern itself.

**Shortest path** shows how two members are connected (step 6.5):

```text
A0000030 to A0001525: 6 relationships
  A0000030 - Device - A0000302 - Address - A0000413 - Phone - A0001525
```

## `PROFILE`: index seek versus label scan

Prefixing a query with `PROFILE` runs it and returns the plan with **db hits** (units of
storage work). Step 6.6:

```text
lookup                                 operators                                    db hits  rows
-------------------------------------  -------------------------------------------  -------  ----
by application_id (unique constraint)  ProduceResults <- NodeUniqueIndexSeek        6        1
by product and status (no index)       ProduceResults <- Filter <- NodeByLabelScan  6468     201
```

The same reading as MongoDB's `explain()`: a seek through the constraint's index, versus
reading every `Application` node and filtering. (The db hit count of the scan varied by a
few between runs.) Create an index (`CREATE INDEX FOR (a:Application) ON (a.status)`) for
properties you filter on often.

## Exporting graph results to tables

Graph algorithms beyond path-finding (connected components, PageRank, community
detection) come with the Graph Data Science plugin, which this guide does not install.
A data engineer usually does not need it: export the edges to a table and compute what
you need in the lake. Step 6.7 exports the identity edges and finds connected components
with union-find (`src/nosqlde/graph.py`), then flags components with three or more
distinct borrowers:

```text
component sizes (applications per component: how many components):
  1: 1487, 2: 404, 3: 16, 4: 4, 5: 1, 6: 1, 7: 1, 8: 2
components with 3 or more distinct borrowers: 8; planted rings: 8; rings found whole inside a flagged component: 8; flagged components with no ring: 0
flagged applications: 45 = 32 planted + 13 extra (9 are other applications by ring borrowers, 4 belong to people linked to a ring member)
components of 2 (households sharing an address, or one person applying twice): 404; not flagged
```

The threshold matters: 404 components of two applications are households (the generator
plants 60) or one person applying twice, and a rule like "flag any shared address" would
flag all of them. Step 6.8 writes the result as tables a warehouse can join:

```text
wrote lake/ch06/edges.parquet (7179 rows) and ring_members.parquet (45 rows)
```

The capstone joins exactly this kind of table to the loan book and finds that ring loans
are far more often 30+ days past due.

The other common data engineering use of a graph is **lineage**: datasets and jobs as
nodes, reads and writes as relationships, and "what is downstream of this table?" as a
variable-length query. The modelling and the export pattern are the same.

## Using the browser

Neo4j Browser is at <http://localhost:7574>. Because the Bolt port is mapped to 7787
(not the default 7687), enter `bolt://localhost:7787` as the connect URL, user `neo4j`,
password `nosqlde-local-only` (a local-only password set in `docker-compose.yml`). Try
`MATCH p = (:Application {application_id: 'A0000030'})-[*1..6]-() RETURN p`.

## Exercises

`exercises/ch06_neo4j.py`:

1. `shared_device_query()`: a Cypher pattern for applications by different people
   sharing a device.
2. `connected_applications(driver, id, max_hops)`: a variable-length traversal.
3. `group_by_shared_identifiers(pairs)`: connected components in plain Python.
4. `export_edges(driver, path)`: write the identity edges to Parquet.

```bash
make check-06
```

```text
Checking solutions/ch06_neo4j.py
  PASS  6.1 shared_device_query: 8 pairs of applications by different people sharing a device
  PASS  6.2 connected_applications: 8 applications within 10 hops of A0000030, 4 within 2
  PASS  6.3 group_by_shared_identifiers: 1916 groups, matches the reference union-find
  PASS  6.4 export_edges: 7179 edge rows written to Parquet

Chapter 6 (Neo4j): 4/4 passed (checked solutions/ch06_neo4j.py)
```

## What is not verified

- Only Community Edition ran. Enterprise features are listed from the Neo4j 5
  documentation; the only one demonstrated is the existence-constraint error.
- The Graph Data Science plugin was not installed or tested.
- Performance at scale (millions of nodes, deep traversals on dense graphs) is not
  measured; the lab graph has about 10,000 nodes.
- The fraud-ring "detection" is a teaching example on planted data, not a validated
  fraud model.

## Further reading

- [Graph database concepts](https://neo4j.com/docs/getting-started/graph-database/)
- [Cypher manual (5)](https://neo4j.com/docs/cypher-manual/5/introduction/), including
  [MERGE](https://neo4j.com/docs/cypher-manual/5/clauses/merge/) and
  [variable-length patterns](https://neo4j.com/docs/cypher-manual/5/patterns/variable-length-patterns/)
- [Constraints](https://neo4j.com/docs/cypher-manual/5/constraints/)
- [Query tuning and PROFILE](https://neo4j.com/docs/cypher-manual/5/planning-and-tuning/)
- [Operations manual: editions](https://neo4j.com/docs/operations-manual/5/introduction/)
