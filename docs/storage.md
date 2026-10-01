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
Native metadata uses three uint32 arrays and one byte per vertex (13 bytes per
vertex plus the container). Adjacency uses reusable four-neighbor blocks of
28 bytes. Low-degree rows use bounded scans; rows reaching degree 32 receive
an open-addressed membership/location index. Neighbor iteration sorts a temporary
native row; edge iteration streams canonical edges instead of materializing a
Python set of the whole graph. High-degree iteration still requires row scratch.

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
identities. It still snapshots **Python algorithm state**: this implementation
does not yet eliminate whole-matcher copying. Native local edge certificates rely
on a sealed storage type with tested two-endpoint mutation semantics; callers
cannot subclass or override its mutators. Custom graph backends retain full
edge-set mutation certificates. Mandatory matching/hierarchy/coloring checks are
not disabled.

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
