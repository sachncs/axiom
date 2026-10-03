# Compact native storage

`Packed` is an explicitly selected storage backend, not a replacement dynamic
matching algorithm or a durable graph service:

```python
from axiom import Matcher, Packed

graph = Packed(128, budget=64 * 1024 * 1024)
graph.ring(2)
matcher = Matcher(128, graph=graph, mode="multilevel")
matcher.insert(0, 4)
assert matcher.graph is graph and matcher.maximal() and graph.check()
```

Source builds require CPython development headers and a C++17 compiler. The
extension has no third-party native runtime library dependency. Wheels are
platform/CPython-version specific; this is not a universal pure-Python wheel.

## Storage and memory contracts

Vertices remain fixed dense IDs; insertion/deletion methods edit **edges**.
Native `Packed` metadata uses three uint32 arrays and one byte per vertex (13
bytes per vertex, excluding vector capacity and container objects). Adjacency
uses reusable four-neighbor blocks of 24 bytes; occupancy is derived from the
row degree and tail-block position rather than stored redundantly in every
block. In the production `Engine`,
partners add 4 bytes per vertex and the hierarchical free-vertex bitmap about
0.127 bytes per vertex. The published-partner first-write index is now sparse:
it has eight inline entries and grows with vertices touched in an active batch,
not with the graph universe. Its dynamic open-addressed capacity is budgeted,
retained for reuse after large batches, and grows with old/new coexistence
accounted. Thus a degree-four graph using roughly one adjacency block per vertex
has an idle structural baseline near 41.13 bytes per vertex: about 41 GB
(38.3 GiB) at one billion vertices, before allocator/capacity slack, active
batch indexes/journals, SQLite, Python, or process overhead. The default 1 GiB
graph budget cannot hold that representation. This is an order-of-magnitude
estimate, not a billion-vertex capacity claim; uint32 block addresses
additionally cap higher-density graphs at fewer than 4.3 billion adjacency
blocks. `Engine.memory()` and
`Packed.memory()` report retained native allocation under the graph budget, not
this broader process footprint.

Moderate-degree rows use bounded scans; rows reaching degree 128 receive
an open-addressed membership/location index. Neighbor iteration sorts a temporary
native row; edge iteration streams canonical edges instead of materializing a
Python set of the whole graph. High-degree iteration still requires row scratch.
This policy avoids a global hash entry for every adjacency of a degree-64 graph.
It trades bounded row scans for substantially less retained memory; large hubs
remain indexed. [ADR 0021](adrs/0021-moderate-row-index-policy.md) records the
evidence and qualification still required. Existing indexed rows may retain their
cache after shrinking; allocation capacity is not reclaimed by logical rollback.

The default native allocation budget is 1 GiB **per graph**, not a process RSS
limit. `memory()` accounts retained metadata, arena, index, and journal capacity.
Arena/index/journal growth also checks the coexistence of old and new native
buffers. Python wrappers/results, allocator overhead, iterator/audit scratch,
reference matcher state, and independently created graph copies are additional.
Allocation failure occurs before either endpoint's logical edge mutation.

`compact()` builds a bounded candidate before publishing it. If coexistence would
exceed the budget, it fails without changing graph contents/version. It preserves
existing logical iterators and transaction-token sequencing. `ring(width)` is an
empty-graph native builder, not a constant-time API: construction is O(n × width).
The current uint32 block addressing permits at most 2^32−1 blocks; this limits
dense billion-vertex graphs even with sufficient RAM. Widening or segmenting block
addresses is required before qualifying those workloads.

## Transactions and failure behavior

`begin()` returns a token scoped to this graph; use `commit(token)` or
`rollback(token)`. Nested transactions and stale tokens are rejected. The active
journal has one thread owner; other threads cannot inspect or mutate its topology.
Matcher closes its managed native journals through one allocation-free group
publication after validating every participant; a stale token cannot partially
commit the group.
Ordinary concurrent graph or matcher use is unsupported. Compaction and ring
publication are prohibited while a transaction is active.

Every real edit records an inverse operation and prior endpoint-index flags before
mutation. Rollback requires no native allocation and restores graph contents,
degrees, edge count, indexing decisions, and logical version. Retained buffer
capacity/free-block layout need not return byte-for-byte to their earlier shape.
Iterators affected by either forward edits or rollback fail rather than exposing
cached transient rows. An internal rollback inconsistency poisons native storage
and subsequent topology operations fail explicitly.

Matcher rollback protects the caller graph and existing managed native graph
identities. The update transaction no longer uses recursive `deepcopy`: enlisted
state uses shallow root retention and bounded owner-specific undo journals.
This does not mean every operation is bounded by the number of touched edges;
some admission, alias, and certificate checks still inspect state-sized
collections, and rebuild paths may construct replacement structures. Native
local edge certificates rely on a sealed storage type with tested two-endpoint
mutation semantics; callers cannot subclass or override its mutators. Custom
graph backends retain full edge-set mutation certificates. Mandatory
matching/hierarchy/coloring checks are not disabled. Paper matching remains
nondurable and is not yet integrated into the SQLite-backed production service.

## Reproduce the measurements

Run sizes sequentially in fresh processes:

```bash
python benchmarks/storage.py --vertices 32000
python benchmarks/storage.py --vertices 128000
python benchmarks/storage.py --vertices 1000000 --seed 599
```

Each run uses average degree 4 by default and 20,000 delete/reinsert pairs. Every
edit commits a one-edit journal. The whole-trace rate includes loop dispatch,
journal operations, and sample recording, but excludes construction, trace
generation, and final audits. Per-operation rates use the sum of instrumented
call durations and exclude between-call overhead. Percentiles are nearest-rank
samples, not service acknowledgment latency. The final audit checks native
invariants and every neighbor row against the exact original ring.

These measurements exclude matching repair, phase/fan operations, durability,
queues, and recovery. They do not qualify million-vertex **Matcher** operation or
billion-vertex support. Continue the full [engineering roadmap](engineering.md).
