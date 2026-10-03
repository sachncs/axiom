# Paper-engine diagnostics

`no-deepcopy-spotcheck.json` records a reproducible 512-vertex working-tree
diagnostic after recursive Matcher snapshot removal. It is not a before/after
causal comparison, release qualification, or evidence for million/billion-node
support. The prior installed-wheel comparisons below have their own runner and
methodology; do not compare those rates directly.

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

## Incremental hierarchy certificates

[hierarchy-certificates.json](hierarchy-certificates.json) compares baseline
`764f652` with the endpoint-certificate candidate on one host using the same
8,192-vertex, sparse, average-degree-four multilevel churn trace: 128 real
updates, seed 42, five timing batches, no full phase rebuild, and one subphase
rebuild. Both versions produce the same final matching certificate and rebuild
counters. Rate rises from 19.70 to 148.65 updates/s (7.55×). Traced transient
peak falls from 4.65 MB to 2.39 MB; process peak RSS falls from 109.8 MB to
102.5 MB in the single memory sample. Source and benchmark hashes, all five
durations and scope limitations are in the JSON.

This diagnostic is not durable service or million-vertex qualification. It
shows that the prior every-update full hierarchy audit dominated the paper
mode at this size; endpoint-local certificates now preserve graph-dependent
invariants, with complete hierarchy audits retained at rebuild boundaries.

## Incremental maximality certificates

[local-maximality.json](local-maximality.json) compares `4ab447c` with the
affected-neighborhood certificate on the same 8,192-vertex, average-degree-four
multilevel churn trace: 128 updates, seed 42, five timing batches. Rate rises
from 148.65 to 228.92 updates/s (1.54×), with unchanged final graph/matching
certificates and rebuild counters. Traced transient memory is unchanged within
measurement noise and RSS differs by 1.52% in a single sample; this is compute
evidence, not a storage claim or release qualification. A separate 512-vertex
profile identifies full auxiliary-index validation as the next cost.

## Incremental auxiliary-index certificates

[auxiliary-certificates.json](auxiliary-certificates.json) compares `6668b6d`
with touched-row certificates on the same seeded 8,192-vertex, average-degree-
four multilevel churn trace. Rate rises from 228.92 to 436.54 updates/s (1.91×),
with identical final graph/matching certificates and rebuild counters. A
separate 512-vertex cProfile comparison falls from 0.1423 to 0.1035 profiled
seconds for 128 updates (27.3%); this is diagnostic, not a throughput claim.
Traced transient allocation changes by less than 0.1%, and single-sample RSS
is effectively unchanged. Full reconstruction remains at rebuilt-root
boundaries; property tests independently run it after each generated update.

## Incremental System cache-row validation

[system-certificates.json](system-certificates.json) compares `c3d443a` with
the stable-root local row validator on the same 8,192-vertex trace. Rate rises
from 436.54 to 610.30 updates/s (1.40×), with unchanged graph/matching
certificates and rebuild counters. At 512 vertices the cProfile time for 128
updates falls from 0.1035 to 0.0733 seconds (29.2%). This is one-host diagnostic
evidence; sampled memory is unchanged. Standalone/new/replaced Systems retain
full cache-row admission; generated tests run complete Lambda/L cache equality
checks after each update. Full phase-owned System bounds are checked at phase
boundaries, not against intermediate live topology.

## System root and row journal

[systems.json](systems.json) captures isolated installed-wheel comparisons of
`d0d4953` and the uncommitted System journal wheel (SHA-256 recorded there) on
one fixed 512-vertex, average-degree-four churn trace. Both modes perform the
same 64 insertions and 64 deletions, have identical repair counters and
certificates, and use three timed repeats. Basic measured 608.90 to 797.18
updates/s; multilevel measured 205.11 to 244.62 updates/s. Transient traced
memory moved from 704,256 to 582,832 bytes (basic) and 1,433,616 to 1,203,568
bytes (multilevel). RSS moved slightly upward for basic and downward for
multilevel; this is too small and host-specific to support a general RSS claim.
The sample is diagnostic, not durable-service or million-vertex qualification.

Independent 128-vertex, 256-update runs hash the full Witness state at all 257
prefixes. The baseline and candidate hashes match in each mode; maximality and
hierarchy certificates are checked after every update. Basic has one phase and
ten subphase rebuilds; multilevel has three phases and 24 subphases. The runner
uses normalized `None` values only for the two new idle undo-handle fields so
the old and new Witness schemas compare the same logical state.

## Hierarchy root retention

[hierarchies.json](hierarchies.json) isolates the Hierarchy migration by comparing
the prior System-journal wheel (`e0ba1365…`) with the clean candidate wheel
(`70bcbbc2…`), using the unchanged runner and 512-vertex/128-update fixed trace.
Every operation outcome, trace digest, final certificate and repair counter
matches. Basic is effectively flat within this small sample (792.92 to 803.52/s;
transient traced bytes 582,832 to 583,064). Multilevel rises from 244.33 to
253.10/s (+3.6%) and transient traced bytes fall from 1,203,568 to 1,115,032
(-7.4%); RSS rises by about 1.0%. Three repeats on one host are diagnostic, not
a general speedup or production-throughput qualification.

An independent 128-vertex, 256-update comparison checks the complete Witness
state at all 257 prefixes for each mode; both prefix sequences match exactly.
Maximality and hierarchy invariants are checked after every update. Both traces
cross phase and subphase rebuilds. Failure injection after a full rebuild on
Adjacency and Packed also restores original hierarchy/partition object identities
and permits retry. The Hierarchy root is still passed to `deepcopy`, but its memo
entry returns the exact original object without traversing it. Other Matcher
state continues to be deep-copied.
