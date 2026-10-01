# ADR 0003: Replace global snapshots with bounded local undo

Date: 2026-10-01. Status: native graph journals implemented; algorithm journals pending.

## Context

`Matcher.__atomic_update` originally enumerated graph edges and used `deepcopy`
before every real update. A local mutation therefore allocated and traversed
global state. Earlier profiling attributed 76.4% of instrumented basic time at
512 vertices to inclusive `deepcopy`; after sparse-index changes a fresh 256-call
profile still attributed approximately 67.6%. Inclusive times overlap and are
diagnostic, not a prediction of achievable speedup.

The snapshot is also a reliability mechanism: it protects matching views,
hierarchy, indexes, counters, coloring/fans where involved, and caller graph
identity. Deleting the snapshot without a complete replacement is unacceptable.

## Decision

Record old values/inverse edits **before** mutation, reserve bounded undo capacity,
validate before commit, and unwind in reverse on failure. Undo must not need a
fresh whole-graph allocation under memory pressure. Protect every participating
structure, not only adjacency. For rebuilds use isolated candidate state and one
validated publication point with bounded coexistence and backlog.

Native graph journals now preserve edge contents, degrees/counts, endpoint-index
decisions, and logical version. Retained allocator capacity/free-block layout need
not be byte-identical. Failed rollback poisons native storage and blocks further
topology operations. Iteration uses a separate mutation epoch: restoring a logical
version cannot make a cached transient row valid again. Candidate publication
preserves token sequencing, preventing stale-token reuse.

Matcher opens journals on distinct existing managed native graphs, including base
phase graphs. Group publication validates every participant before an
allocation-free commit pass; it cannot close an earlier journal then discover a
stale later participant. Python algorithm state still uses the snapshot reference
path. The approved native production matcher must journal its compact partner
state/counters as well as its graph.

## Consequences and alternatives

Keep reference snapshots and failure-injection/differential tests until each
replacement is certified. Whole-state copy-on-write, partial graph-only undo, and
disabling rollback were not selected as the final solution: they retain global
costs or leave split state. Journal bounds and failure behavior become explicit
admission/transaction contracts. In-memory undo is not crash durability (ADR 0007).

## Evidence

Native tests cover budget rejection, promotion/demotion rollback, stale/nested
tokens, thread ownership, iterator invalidation, group precondition failure,
snapshot allocation failure, and failed basic/multilevel phase updates followed
by successful reuse. A standalone 200,000-edit C++ differential stress test passed
ASan/UBSan. Full Python algorithm snapshot elimination is **not implemented**.
