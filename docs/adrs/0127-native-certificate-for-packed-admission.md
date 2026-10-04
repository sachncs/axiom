# ADR 0127: Use the native certificate for Packed graph admission

- Status: implemented; constrained Linux memory qualification pending
- Date: 2026-10-04

## Context

The first installed 1,000,000-vertex Linux resource worker failed under its
512 MiB address-space limit during `Matcher` admission. Validation retained
`list(graph.edges())`, a Python edge set, a second adjacency edge set, and
per-row neighbor lists while validating built-in `Packed`. This duplicated
millions of edges in Python. The custom-graph protocol still needs exhaustive
cross-view validation because those implementations are caller supplied. The
subsequent worker passed admission but exposed a separate paper-index peak,
addressed by ADR 0128; the constrained qualification remains open.

## Decision

For the non-subclassable native `Packed` type only, use its native `check()`
integrity certificate after validating the graph universe and required protocol methods.
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
512 KiB of traced Python temporary memory. The complete local suite passes
(1,270 passed; one optional matplotlib report skipped), including follow-on
compact-row and direct-build changes. A subprocess test also imports and uses
the paper/storage APIs while simulating an unavailable `fcntl`, and confirms
Durable/Service reject the non-POSIX boundary. The latest installed job passed
the old `adjacency_edges` admission point and failed later in paper index
construction; ADRs 0128–0129 address that second peak, but a successful
constrained Linux resource run is still required.
