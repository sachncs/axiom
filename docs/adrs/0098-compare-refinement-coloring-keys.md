# 0098: Compare refinement coloring keys without materializing edge sets

Date: 2026-10-04. State: implemented; component allocation and latency probe
only, not full refinement or product qualification.

## Context

`refine_hierarchy` verifies that Paper returned exactly one color per selected
matching edge. The successful path compared `set(coloring)` with
`set(previous.M)`, allocating two additional edge-sized hash tables before
building the recursive color classes.

## Decision

Compare `coloring.keys()` directly with `previous.M`. Python's dictionary key
view performs set equality without copying either collection. Preserve the
existing detailed set-difference construction only in the exceptional
incomplete-coloring diagnostic path.

## Evidence and limits

On a 100,000-edge dictionary/set component, seven repeats of five checks gave
median 2.45 ms for materialized equality and 0.90 ms for key-view equality.
`tracemalloc` peak for one comparison fell from 8,389,040 bytes to 112 bytes.
Both returned equal results. A focused refinement test supplies a dict subclass
whose key iteration raises; complete hierarchy validation succeeds, proving the
ordinary path does not call `set(coloring)`.

These are local component measurements; color production, class construction,
refinement, allocation outside the comparison, and end-to-end performance are
not represented. Other O(m) color-class storage remains unchanged.
