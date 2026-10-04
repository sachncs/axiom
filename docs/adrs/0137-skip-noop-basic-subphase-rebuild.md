# ADR 0137: Skip unchanged Basic subphase synchronization

- Status: implemented; constrained million-vertex validation pending
- Date: 2026-10-04

## Context

Basic configures a subphase every approximately `n^(2/3)` updates. Before this
change, every boundary filtered the seed matching, ran seed augmentation,
rebuilt auxiliary H/H-tilde indexes by sorting and scanning all of `U`,
resynchronized the seed color class, and audited maximality over all vertices.
On a million-vertex degree-four graph, the initial paper system has `A=B=empty`,
`U=V`, and an empty seed matching. With no deleted seed edge and no saturated
vertex, seed augmentation cannot change M1; the global rebuild and maximality
scan therefore repeat without changing state. This is a concrete
size-dependent cost identified after the hosted worker reported only
200,192/1,040,000 updates in 240.985 seconds.

## Decision

At subphase boundaries, retain the existing stale-seed cleanup. Detect whether
any seed edge was removed; if A/B is nonempty, run the normal seed augmentor and
record whether it found an augmenting path. Return before class replacement,
auxiliary rebuild, displaced-vertex repair, and the global maximality audit only
when neither cleanup nor augmentation changed the seed. If either changes M1,
keep the full existing synchronization and validation path.

When A and B are empty, skip seed augmentation entirely: its search domain is
the saturated set A∪B, so there can be no candidate. This preserves subphase
counters and accounting while avoiding a set allocation and empty search.

## Consequences

- In an unchanged empty-seed phase, a boundary no longer sorts/scans all of U
  or scans all graph vertices for maximality.
- Any stale seed deletion or successful augmentation still takes the complete
  synchronization path, including maximality certification.
- The optimization does not change user-visible matching state and does not
  weaken ordinary update-local maximality certificates.
- Million-vertex throughput and adversarial subphase behavior still require
  hosted qualification; the previous 830/s result predates this optimization.

## Verification

A deterministic test places Basic immediately before a subphase boundary,
forces an edge update with empty M1/A/B, and makes global auxiliary rebuild and
maximality methods fail if called. The update succeeds, advances the subphase
counter, and a subsequent independent full audit passes. Deleted-seed and
nonempty-seed tests pass, including exact Witness rollback for a failed update
at a subphase boundary across both graph backends and matching modes. Full
suite: 1,276 passed, one optional performance-report test skipped because
`matplotlib` is unavailable. Ruff and mypy pass. Hosted constrained throughput
and adversarial subphase qualification remain open.
