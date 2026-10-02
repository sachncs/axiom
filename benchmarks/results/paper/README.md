# Paper matching-view diagnostic

[views.json](views.json) retains all three installed-wheel results, including
per-operation samples, query latency, memory, certificates and artifact provenance.
The unchanged runner comes from `aaafdf9`. Each process uses `python -I`; timing,
latency, queries and traced memory are separate passes. No local tests, builds or
Astro preview overlap these sequential runs.

The fixed workload is basic mode with the Adjacency backend, 2,048 vertices,
4,096 starting edges, seed 7, 64 real insertions and 64 real deletions. Three batch
timing repeats produce each rate. All runs agree on the trace hash, operation
outcomes, final matching certificate and repair counters; no phase/subphase
rebuild occurs. This does not exercise durable acknowledgments or the million-
vertex production target.

| Installed source | Real updates/s | Transient traced bytes | Process peak RSS bytes |
| --- | ---: | ---: | ---: |
| `aaafdf9` accounting journal | 108.00 | 3,131,600 | 44,040,192 |
| `39c36c8` matching journal, full alias walk | 100.09 | 2,852,680 | 44,220,416 |
| `9d2209e` matching journal, uniqueness proof | 123.11 | 2,852,552 | 44,089,344 |

The first matching journal reduced transient traced memory by 8.9% but measured
7.3% slower. Retaining that regression is important: removing copies alone did
not improve compute. The uniqueness-proof follow-up measured 14.0% faster than
the accounting-only baseline and 23.0% faster than the full-walk journal, while
retaining the traced-memory reduction. RSS is essentially unchanged, not reduced.
These are single-host diagnostic comparisons with three repeats, not statistical
cross-host qualification or evidence of constant-time paper updates.

The fast path applies only to exact builtin matching containers with exactly
three strong references on GIL-enabled CPython. Shared views, other interpreters
and free-threaded builds retain the conservative walk. Remaining paper snapshots
and global certificates still run. See [ADR 0025](../../../docs/adrs/0025-matching-view-journal.md)
for ownership, failure behavior and the active migration boundary.

## Color-class follow-up

[classes.json](classes.json) retains the next journal's initial full-walk
regression and ownership-proof correction, using the same installed runner,
configuration and pass separation. The intermediate uncommitted wheel is identified
by its artifact hash and changed-package file hashes, not assigned a fictional
commit. The final package code matches `2730390`.

| Installed candidate | Real updates/s | Transient traced bytes | Process peak RSS bytes |
| --- | ---: | ---: | ---: |
| `9d2209e` matching-view baseline | 123.11 | 2,852,552 | 44,089,344 |
| Intermediate class journal, full alias walk | 99.72 | 2,824,696 | 44,515,328 |
| `2730390` class journal, ownership proof | 126.50 | 2,824,504 | 44,105,728 |

All operation outcomes, trace/final matching hashes and repair counters agree.
The initial full walk measured 19.0% slower than the matching-view baseline.
Accounting for known seed/class sharing removes that traversal for uniquely owned
GIL-enabled CPython containers. The final candidate measured 2.8% faster with 1.0%
less transient traced memory than that baseline; RSS remains essentially unchanged.
The small rate difference is diagnostic, not a statistically established speedup.
This sparse fixture has no phase/subphase rebuild and mostly empty color classes:
it exposes admission overhead, not dense color-class or rebuild performance.
Separate dense, per-mode and durable qualification still remains necessary.

## Shared System cache deltas and union-free membership

[deltas.json](deltas.json) compares installed `2730390` and `d0d4953` using the
unchanged archived runner, sequential isolated interpreters and the same hardware
and allocator policy. Each mode uses 512 vertices, average degree four, seed seven,
128 real churn updates and three timed repeats. Diagnostic latency, queries and
memory remain separate passes; no tests, builds or preview overlap measurement.

| Mode | Before real updates/s | After real updates/s | Before/after transient traced bytes |
| --- | ---: | ---: | ---: |
| basic | 574.28 | 585.56 | 704,320 / 704,256 |
| multilevel | 117.36 | 199.35 | 1,434,576 / 1,433,616 |

The multilevel rate measured 69.9% higher after removing per-neighbor/edge
partition-union allocations; basic measured 2.0% higher. These single-host
three-repeat results are scoped diagnostics, not cross-host repeatability or
durable throughput qualification. Traced memory and RSS are essentially unchanged
(RSS rose from 34,504,704 to 34,766,848 bytes in basic and from 38,043,648 to
38,584,320 bytes in multilevel); do not advertise lower resident memory.
All operation outcomes, trace/final matching hashes and repair counters agree.
The performance cases exercise two basic and five multilevel subphase rebuilds,
but no full phase rebuild.

A separate installed differential run uses 128 vertices, average degree four,
seed seven and 256 real churn updates. It captures and hashes the entire Witness
state initially and after every update: all 257 prefixes agree in each mode.
Basic ends with one phase and ten subphase rebuilds; multilevel ends with three
phase and 24 subphase rebuilds. Maximality and hierarchy certificates are checked
separately, not inferred from hash equality. The report retains the shared hashes,
full accounting and executable Python procedure. Run that procedure with each
isolated wheel interpreter (`python -I -c ...`), using the benchmark file archived
from the declared runner revision, and compare the resulting JSON outputs.

See [ADR 0027](../../../docs/adrs/0027-system-cache-deltas.md). The shared delta
boundary still relies on snapshots for System/Hierarchy undo; it is not their
journal migration, an exact recovery codec, or a durable Service implementation.
