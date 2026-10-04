# ADR 0127: Use the native certificate for Packed graph admission

- Status: implemented; constrained Linux memory qualification pending
- Date: 2026-10-04

## Context

The installed 1,000,000-vertex Linux resource worker failed under its 512 MiB
address-space limit before reaching the exhaustion stages. `Matcher` validation
retained `list(graph.edges())`, a Python edge set, a second adjacency edge set,
and per-row neighbor lists while validating its built-in `Packed` graph. This
duplicated millions of edges in Python and caused `MemoryError` during ordinary
construction. The custom-graph protocol still needs the exhaustive cross-view
validation because those implementations are caller supplied.

## Decision

For the immutable native `Packed` type only, use its native `check()` integrity
certificate after validating the graph universe and required protocol methods.
Reject a false result. Keep the existing exhaustive edge/adjacency comparison
for `Adjacency` and caller-defined Graph implementations. Do not catch native
allocation failure and treat it as successful validation; it must reject
construction.

The native checker independently verifies row links, endpoint bounds, loops,
reciprocal adjacency, duplicates, degree/count consistency, block ownership,
free-list accounting and index locations. It uses native temporary memory
proportional to packed storage rather than Python tuple/set objects for every
edge. This is not a general promise that validation is allocation-free, nor a
change to graph concurrency semantics.

## Consequences

- Default durable construction no longer needs several simultaneous Python
  copies of the full Packed edge set.
- Custom graph implementations retain strict cross-view validation and its
  conservative memory cost.
- Native `check()` can still need a bounded ownership bitmap and row workspace;
  a hard memory failure remains an explicit construction failure.
- The unit allocation regression measures Python-tracked temporary peak on a
  60,000-edge graph. Only the installed Linux 512 MiB worker can establish
  whether this is sufficient for the million-vertex envelope.

## Verification

The direct admission test validates a 60,000-edge Packed graph with less than
512 KiB of traced Python temporary memory. The full local suite passes (1,267
passed, one optional matplotlib report skipped), including the allocation
regression. A subprocess test also imports and uses the paper/storage APIs while
simulating an unavailable `fcntl`, and confirms Durable/Service reject the
non-POSIX boundary. Hosted Windows and constrained Linux runs are still
required. The previous installed job failed inside the old `adjacency_edges`
construction before this optimization; no constrained Linux result is claimed
yet.
