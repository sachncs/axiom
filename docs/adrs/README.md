# Architecture decision records

These records explain the scalability/reliability work, including what is being
replaced, why, the guarantees retained, alternatives, and verification still
required. **Accepted design is not evidence of completed implementation.**
Dates use the project's user-facing calendar (1 October 2026).

| Record | Decision | State |
| --- | --- | --- |
| [0001](0001-production-qualification.md) | Qualify 10k durable real updates/s at one million vertices | Target accepted; qualification pending |
| [0002](0002-native-storage.md) | Compact native storage instead of per-vertex Python sets | Implemented; storage-only evidence |
| [0003](0003-bounded-transactions.md) | Bounded undo instead of whole-state `deepcopy` | Native graph journals implemented; algorithm-state migration pending |
| [0004](0004-sparse-phase-indexes.md) | Sparse phase overlays instead of eager empty maps | Implemented and regression-tested; short-trace evidence only |
| [0005](0005-incremental-certificates.md) | Immediate incremental certificates, not disabled checks | Native edge certificates implemented; matching certificates pending |
| [0006](0006-native-production-matcher.md) | Separate native production matcher, retaining the paper engine | Explicitly approved by user; implementation pending |
| [0007](0007-durability-and-publication.md) | WAL, bounded group commit, coherent query versions and recovery | Accepted direction; implementation pending |
| [0008](0008-resource-and-release-gates.md) | Single ownership, resource limits, independent qualification gates | Partially implemented; full-service gates pending |

The [engineering assessment](../engineering.md) remains the complete roadmap;
[storage contracts](../storage.md) describe the delivered container. Subsequent
changes must update the relevant record's implementation/evidence section rather
than silently changing an accepted contract or declaring an unfinished goal done.

## What is not being abandoned

- Proper **maximal**, not necessarily maximum-cardinality, matching.
- Deterministic behavior under the specified backend and update order.
- All-or-nothing accepted updates and coherent committed graph/matching queries.
- Explicit rejection, rollback/fail-stop behavior, and independent verification.
- The existing research engine, including its coloring/fan/hierarchy regression
  requirements and the reference snapshot path until replacements are certified.

The changes remove implementation overhead and introduce an explicitly different
production algorithm. They do not silently weaken the paper engine or claim its
theoretical bounds for the new backend.
