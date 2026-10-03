# ADR 0058: Reuse the level-one System construction

Date: 2026-10-03

## Context

A full multilevel rebuild retained a level-one System as `phase_base_system`,
then called `build_hierarchy`, which independently ran the same full greedy
matching, partition, promotion, and cache-construction algorithm for level one
again. The hierarchy must own a mutable System because recursive refinement
changes its partitions and graph binding; the retained phase-base System must
remain independent.

## Decision

Add an optional `first` System input to `build_hierarchy`. It must be idle and
bound to the same graph and initial z parameter. The hierarchy builder takes
ownership of this System and may mutate it during refinement. Full rebuilds
build the inherited phase-base System once, copy it onto the same phase graph,
and pass that detached copy as `first`. Standalone callers that omit `first`
retain the existing build-from-scratch behavior.

The final rebuild boundary continues to validate the retained phase-base
System and the complete hierarchy. The copy is not shared with the phase-base
root.

## Alternatives considered

- Run the complete level-one builder twice: rejected as duplicate graph-wide
  greedy/promotion work.
- Share one mutable System between phase base and hierarchy: rejected because
  recursive refinement mutates partitions, matching, graph binding, and lists.
- Skip full end-to-end hierarchy validation: rejected; existing rebuild
  certificates remain enabled.

## Evidence and limits

On an 8,192-vertex degree-four ring with z=4, five isolated samples measured
two level-one builds at a 44.7 ms median versus 28.8 ms for one build plus
System copy (about 35% lower for that stage). This excludes hierarchy
refinement. On a 512-vertex degree-four ring with levels [4, 2], three complete
build samples were 820 ms for two builds and 816 ms for build-plus-copy; this
is within measurement noise, and no end-to-end speedup is claimed. A full
8,192-vertex hierarchy timing exceeded 80 seconds and was interrupted during
coloring validation; it is explicitly not a benchmark result. The current
paper refinement/coloring path remains a major scale bottleneck.

Tests compare supplied-System output against ordinary construction, prove the
retained original remains independent and valid, reject graph/z/journal
mismatches, and exercise the Matcher rebuild path. Full test and static checks
are required before publication.

## Consequences

The rebuild avoids a second full level-one construction but copies the base
System and reindexes its rows to create isolated mutable ownership. Small
end-to-end measurements do not show a meaningful speed improvement because
refinement dominates. Large rebuild qualification is still missing; storage,
coloring/refinement complexity, and durable paper integration remain active.
