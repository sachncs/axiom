# Explicit native matching core

`axiom.engine.Engine` implements the production algorithm approved in
[ADR 0006](adrs/0006-native-production-matcher.md). It is separate from `Matcher`
and the paper/coloring/hierarchy engine. **It is not yet a durable service.**

```python
from axiom.engine import Engine

engine = Engine(128, budget=64 * 1024 * 1024)
engine.ring(2)
assert engine.insert(0, 4)
assert engine.delete(0, 1)
assert engine.check()
version, matching_edges, next_vertex = engine.page(limit=64)
```

## Algorithm and certificates

The graph is private native adjacency; partners occupy one uint32 array (four
bytes per vertex), with a matching-size counter. Insertion pairs two free
endpoints. Deletion of a matched edge frees its endpoints and deterministically
rematches each against its smallest available neighbor. Ordinary edits do not
use `deepcopy`, whole-matching recomputation, coloring/hierarchy construction,
or a full graph scan. High-degree deletion can still scan large neighborhoods.

Every real edit certifies endpoint membership/degrees/count/version, symmetric
live partner edges, and maximality at affected partner dependencies. Only deleted
matching endpoints can become newly free; rematching only shrinks the free set.
The separate full audit walks every graph/partner dependency independently of
the local certificate helper. Python/C++ reference tests check exact deterministic
decisions, topology, properness, and maximality.

## Transactions, queries, and limits

- `insert`/`delete` return whether an edge really changed. Self-loops, duplicate
  insertion, and absent deletion return false without changing logical version.
- Standalone edits commit in memory. `begin`/`commit`/`rollback` support explicit
  batches. A native edit failure aborts the entire batch, including earlier edits.
  Binding argument/type rejection occurs before the native edit and leaves an
  existing batch unchanged; its owner must close it. Stale/nested tokens reject
  without closing a valid active batch.
- Active transactions are thread-owned; public topology/partner/size/version/page
  reads reject unpublished state, even for the owner. `check` is an owner audit;
  `memory` exposes only allocation/status diagnostics. No writable graph or
  partner-map escape hatch is exposed. Ordinary access requires a single owner.
- Graph and partner old values are journaled before mutation. At most six partner
  writes occur per matched-edge deletion. Rollback allocates no native memory and
  restores topology, partners/count, and logical version, not retained buffer
  capacity/free-block layout. Unexpected rollback state poisons the engine.
  A certificate failure also rolls back and poisons it: successful undo is not
  proof that a detected internal invariant failure is safe to ignore.
- `partner`, `size`, `num_edges`, and `degree` are bounded point queries. `page`
  returns `(version, matching_edges, next_vertex)` and scans at most **4096
  vertices**, not until 4096 edges are found. Empty/sparse pages remain bounded.
  Supply the first page's version to later pages; intervening updates reject a
  stale version. Historical version retention is not implemented.
- One native budget covers graph/partners/journals/metadata, including old/new
  growth buffers and ring candidates. Python objects, allocator overhead, audit
  scratch, page results, and total RSS are additional. Fixed uint32 addressing
  retains the limits in ADR 0002. Service-level resource limits remain pending.

## Measurements, not completion

```bash
python benchmarks/engine.py --vertices 32000
python benchmarks/engine.py --vertices 128000
python benchmarks/engine.py --vertices 1000000 --seed 599
```

The benchmark deletes distinct live ring edges, inserts distinct absent non-ring
edges, and performs one timed partner query per pair plus sampling queries. It
maintains two edges per vertex. Whole-trace timing includes selection, Python
query/update dispatch, and latency recording. Exact expected graph and proper
maximal matching are independently verified through public queries, alongside
the full native audit. Initialization/final audits are reported separately.

Three fresh million-vertex runs of 20,000 pairs produced approximately 686k–720k
real updates/s and 134.5–134.6 MB peak RSS. These are **short in-memory** results,
not stationary long-run churn, maintenance-inclusive soak, or durable throughput.
Raw records: [599](../benchmarks/results/engine/million-599.json),
[600](../benchmarks/results/engine/million-600.json),
[601](../benchmarks/results/engine/million-601.json).

Measured core: commit `9802ddb`; local environment: Apple M3 Pro, 18 GiB RAM,
macOS 26.7.1, CPython 3.14.7. Each trace contains 40,000 real changes and 20,000
timed partner queries, and lasts only approximately 56–58 ms. Native allocation
is 45,000,336 bytes after ring construction and 73,000,528 after churn; process
RSS also includes Python trace data and final audit scratch. Do not extrapolate
these measurements to one billion vertices, hardware-independent latency, or
durable capacity.

Verification at this checkpoint: 482 Python tests pass (83.57% Python source
coverage; this does not measure C++ coverage), 97 focused tests pass under
optimized Python, and native ASan/UBSan runs pass 200,000 storage edits plus
100,000 matching edits. Clean isolated wheel and source-distribution installs
exercise both the existing paper matcher and the new native core/rollback.
CI additionally builds/tests supported CPython versions; local Python 3.14
results do not establish support for that version.

WAL/checkpoints, durability barriers, operation-ID deduplication, bounded service
admission, persistence failures/recovery, maintenance-inclusive soak, and the
accepted 10k durable-update qualification remain pending. `commit` must not be
presented as a durable acknowledgment. See [ADR 0007](adrs/0007-durability-and-publication.md).
