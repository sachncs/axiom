# ADR 0097: Use monotone U progress instead of full cycle snapshots

Date: 2026-10-04
State: Implemented; other graph-sized refinement allocations remain

## Context

Each `refine_hierarchy` promotion pass captured `frozenset(new_u)`,
`frozenset(new_a)`, and `frozenset(chosen)` to detect a repeated state. U is
monotone: `promote` only removes a vertex and no code in the loop inserts one.
The loop's `changed` flag is set only after promotion paths. A call that finds
the vertex already removed can set the flag only after another promotion has
already reduced U in that same pass. Therefore every continuing pass must have
a strictly smaller U set, making an exact full-state repetition impossible.

## Decision

Remove the three full-state cycle-key copies and retain one integer, the
previous U cardinality. At the end of a continuing pass, require
`len(new_u) < previous_u_size`, otherwise fail closed with a diagnostic. Update
the scalar and continue. This keeps a deterministic nontermination guard while
making its state O(1) rather than O(n+m). Sparse degree state is handled
separately by [ADR 0096](0096-sparse-refinement-degrees.md).

## Correctness evidence

The sparse refinement regression patches `frozenset` construction to fail and
still obtains a certified hierarchy. Existing tests exercise promotion, U-to-B
witness repair, deferred deletions, cache state, and complete hierarchy checks.
Four independent baseline/candidate fixtures (star, path, clique, and seeded
random graph) had byte-identical `Witness` state after adapting the baseline
Hierarchy root to the comparison schema. In each case both outputs passed the
full hierarchy certificate.

The scalar guard is itself a checked invariant: any future branch that sets
`changed` without decreasing U fails immediately rather than looping or
silently relying on a probabilistic hash.

## Measurement and limits

Three alternating full refinements on a 20,000-label graph with a four-edge
star, z=4→2, compared the pre-change implementation with the candidate that
also includes ADR 0096's sparse degree storage. Both results passed
`Hierarchy.check()` and had the same two-edge final matching. Baseline elapsed
times were 1.275001, 1.122152, and 1.129483 s; candidate times were 1.121002,
1.059947, and 1.060975 s. Median elapsed time fell from 1.129483 to 1.060975 s
(6.07%). Traced peak remained effectively unchanged: 18,128,312 versus
18,128,296 bytes. Output state and other temporary indexes dominate this small
fixture's peak; no total memory reduction is claimed. Full connected/dense
repeats, process RSS and durable update qualification remain open.

## Alternatives

- Keep exact frozenset keys and clear them after U shrinks: rejected because
  strict U monotonicity already gives an exact progress measure and each key
  copies O(n+m) state.
- Use a digest/hash of the state: rejected because collision risk would change
  correctness behavior.
- Remove the termination guard entirely: rejected; the scalar strict-progress
  assertion keeps fail-closed detection if the algorithm changes.

## Follow-up

Continue profiling the retained `old_u` copy, frontier/partition sets, selected
matching and phase graph snapshots. Recheck the progress proof whenever a branch
can add to U or set `changed` independently of promotion. Durable basic/multilevel
integration and service qualification are still separate required work.
