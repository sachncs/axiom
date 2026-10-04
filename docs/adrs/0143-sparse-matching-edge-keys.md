# ADR 0143: Store matched edges as sparse packed integer keys

- Status: implemented; full constrained service qualification pending
- Date: 2026-10-04

## Context

`Matcher.matched_edges` must be a general edge-set representation. It is used
by independent certificates and candidate checks that must be able to represent
overlapping edges, including invalid candidates. A partner array cannot express
such sets: assigning a second incident edge would overwrite the first and hide
the invariant violation.

The first replacement for Python `(u, v)` tuple-set storage used another
`Packed` graph as the matching-edge index. This avoided tuple objects, but each
`Packed` allocates vertex-indexed metadata even when it contains no edges. At a
million vertices, an empty instance accounts for 13,000,264 bytes of metadata.
That is an O(n) cost for an index whose logical contents are O(m), in addition
to the primary graph and the compact partner array.

The cost was material under the enforced 512 MiB process address-space gate.
Hosted Multilevel qualification at commit
[`fdf9e2c`](https://github.com/sachncs/axiom/commit/fdf9e2c6246ae0a0c775c5f187026ab69a43b0d0)
failed during startup
recovery in `Matcher.refresh()` while `MatchingIndex.add()` called
`Packed.add_edge()` and raised `MemoryError`. The failure occurred while
constructing the matching index, before the update workload began.

## Decision

Represent each canonical undirected edge `(u, v)`, with `u < v`, as one Python
integer key `(u << 32) | v` in a sparse integer set. Keys reserve 32 bits for
each endpoint. The set and its integer objects grow with the number of retained
edges, without allocating vertex-sized `Packed` metadata. Keep support for
overlapping edges so independent matching and candidate invariants remain
checkable. A partner-backed representation is rejected for this general
edge-set role.

The representation is sparse, not overhead-free: Python set capacity,
integer-object overhead, allocator behavior, and temporary growth all consume
memory. The component probe below is not a process-memory or whole-service
qualification.

## Evidence and qualification status

- A local deterministic probe inserted 500,000 disjoint edges into a
  one-million-vertex `MatchingIndex`. `memory()` reported **32,777,428 bytes**
  (about 32.8 MB decimal). This is the set table plus the retained integer-key
  object sizes; it excludes interpreter/runtime state, allocator fragmentation,
  transient resize peaks, graph storage, and the rest of the process.
- The rejected `Packed` implementation raised `MemoryError` in the hosted
  Multilevel 512 MiB job for run
  [37198763484](https://github.com/sachncs/axiom/actions/runs/37198763484),
  at commit `fdf9e2c`.
- Hosted CI for HEAD `e4824c9` is run
  [37199582633](https://github.com/sachncs/axiom/actions/runs/37199582633).
  Basic acknowledged 1,000,000 updates in 111.755 s (~8.9k/s, update-only)
  and passed backup and exact memory-pressure recovery, but disk-pressure
  recovery raised `MemoryError` while rebuilding a `lambda_lists` array.
  Multilevel advanced further but failed during startup while snapshotting
  `matcher.graph` into the initial `phase_base_graph`. **Neither mode is fully
  qualified at 512 MiB.** Mixed update/query load was not present in that run;
  the component memory probe does not qualify either mode or the service.

## Consequences

- Matching-edge membership no longer adds a second O(n) `Packed` metadata
  allocation; retained key storage is proportional to the matching edge count.
- The index preserves general edge-set semantics needed by independent
  invariant checks, unlike a partner-only encoding.
- Memory remains Python-container-dependent and must be assessed together with
  graph, hierarchy, durable-service, query, and transient allocations under the
  hard process limit.
- No throughput, full-process memory, recovery, or production-scale guarantee
  follows from the local 500,000-edge measurement. Both paper modes still need
  the complete hosted resource and mixed-query qualification.
