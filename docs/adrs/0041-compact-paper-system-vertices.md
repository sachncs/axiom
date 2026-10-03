# ADR 0041: Compact dense paper-system vertex and degree state

Date: 2026-10-03

## Context

The earlier sparse-cache work removed empty `lambda_lists` and `L_lists` rows,
but a large paper `System` still retained a Python `set` for a dense `U`
partition. `System.build()` also allocated a Python dictionary entry and an
integer key for every vertex just to count the degree of the current matching.
These are representation costs, not graph-theoretic requirements: vertex IDs
are dense and matching degree is a small nonnegative integer.

## Decision

- Represent sufficiently dense `U` partitions with `Vertices`, a fixed-universe
  indexed membership array plus an ordered packed member array. Keep ordinary
  Python sets for sparse `U` partitions. The current crossover is one member
  per twelve possible vertices; this is an initial measured-memory policy, not
  a universally optimal constant.
- Store `System.build()` matching-degree counters in an unsigned integer
  `array`, choosing a 32-bit element when it can represent the vertex range and
  a 64-bit element otherwise. The standalone legacy `switch()` dictionary
  interface is unchanged.
- Derive the `U` population count from `n - |S|`; the greedy degree cap ensures
  every vertex belongs to exactly one of these sets before U-U matching edges
  are removed. This avoids a redundant full-universe counting pass.
- Preserve deterministic promotion order, public `System` behavior, the
  existing Python-set fallback for sparse partitions, and exact matching
  certificates. Do not claim a paper asymptotic or production-path change.

## Alternatives considered

- Keep Python dictionaries and sets: simplest compatibility, but retain a
  large hash-table and boxed-integer cost for dense per-vertex state.
- Use only a bitmap: membership is compact, but iterating the ordered members
  required by current paper routines would need a full-universe scan.
- Use packed arrays for every `U`: rejected because the position index costs
  memory even when the partition is very sparse.
- Replace the paper engine with the native production matcher: out of scope;
  algorithm identity and paper guarantees must remain explicit.

## Evidence and limits

On the current CPython host, a standalone `tracemalloc` allocation for one
million Python integer keys mapped to zero retained 73,933,928 bytes. A
one-million-counter unsigned `array('I')` retained 4,000,264 bytes (94.6% less).
For a full one-million-label `U`, the indexed position/member representation
uses about 8 MB of packed payload, compared with about 74 MB for the equivalent
Python set. These isolated representation measurements establish only local
memory arithmetic; they exclude graph storage, allocator slack, Matcher state,
rebuild copies, and process RSS. They say nothing about throughput.

The full regression suite, including basic/multilevel rebuild and rollback
tests, is required for each implementation change. Fresh-process paper-mode
memory and update-throughput comparisons remain required before treating this
as a qualified end-to-end improvement. Dense `U` conversion currently depends
on the `Vertices` 32-bit vertex-label bound; the existing native graph has the
same bound, while larger custom graph implementations are not qualified.

## Consequences

Dense paper-system state uses substantially fewer Python objects, while sparse
sets remain available and deterministic member order remains stable for an
unchanged edit sequence. `Vertices` is a bounded set-like implementation, not
a drop-in implementation of every Python `set` method. Remaining state-sized
work includes phase graph copies, other certificates/admission walks, `A`/`B`
sets, and the still-active durable paper integration. Billion-vertex support
is not implied.
