# ADR 0095: Use path-local undo for paper System.switch

Date: 2026-10-04
State: Implemented; the switch primitive is not called by the current build path

## Context

`system.switch` copied the complete matching and degree dictionary before each
alternating search, including searches that found no augmenting route. After a
route, it modified path edges, zeroed every degree entry, and recounted every
matching edge. The operation's mutation footprint is the source edge plus the
alternating path; whole-state copies and recounts scale with unrelated graph
state. Repository search finds no internal callers today, but `switch` remains
a documented public paper primitive and must retain its own tested contract.

## Decision

Search remains read-only. After finding a route, derive each affected edge's
final membership in a path-sized map, compute net endpoint degree deltas, and
check capacity plus the existing saturated-vertex invariant before mutation.
Commit only changed edge memberships and endpoint degree values. Capture
before-images only for those changed edges/endpoints; if a set/dictionary write
raises, restore those cells and re-raise. Failed searches and rejected local
preconditions leave input objects untouched. No complete M/degrees copy or
global degree recount remains in `switch`.

Precondition: `M` is a live graph-edge subset and `deg_M` is the exact per-vertex
degree map for M, with all degrees at most z. As before, this routine assumes
its caller maintains the paper System invariants; it is not a full graph audit.

## Correctness evidence

Tests cover a saturated cycle with no route (and forbid whole-state copy
constructors), a successful 3-vertex route with exact expected M/degrees, an
exception after a partial edge commit, and an exception during degree commit.
Both failure-injection cases require exact state restoration. A deterministic
1,000-case differential run over random small graphs, valid degree-bounded M,
and z in 1..3 produced identical return values, M sets and degree maps compared
with the pre-change implementation.

## Measurement and limits

Three alternating runs use a 20,000-vertex `Packed` graph, 19,998 matching
edges in disjoint saturated six-cycles, a source adjacent to one cycle vertex,
and no augmenting route. Input construction is excluded. Both versions return
False with unchanged matching and degree state. Baseline elapsed times were
0.371, 0.254, and 0.205 ms; candidate times were 0.016, 0.011, and 0.008 ms.
Median time fell from 0.254 to 0.011 ms (95.67%). Median traced peak fell from
1,639,936 to 1,232 bytes (99.925%). This specifically measures the failed
search path; successful path lengths, process RSS, and end-to-end refinement
remain unqualified. The primitive currently has no in-repository callsites.

## Alternatives

- Keep complete snapshots/recounts: rejected because search may fail without
  mutation and successful changes touch only the route.
- Journal writes but retain global recount: rejected because recount work still
  scales with unrelated M and n.
- Trust the path without any postcondition: rejected; touched capacity and the
  saturated-vertex rule are computed before commit, while injected mutation
  failures restore exact local state.
- Apply this optimization to callers by reinterpreting the primitive or
  changing M semantics: rejected; paper invariants and algorithm selection stay
  explicit.

## Follow-up

Determine whether `switch` is intended to remain public and ensure production
paper hierarchy paths exercise the right switching primitive. Do not claim
end-to-end benefit until a real caller reaches this route and is qualified.
Continue migrating the remaining graph-sized hierarchy snapshots and durable
paper integration.
