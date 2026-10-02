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
