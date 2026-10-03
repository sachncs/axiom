# 0040: Store only nonempty System cache rows

Date: 2026-10-03. Status: implemented; full paper-engine qualification remains active.

## Context

After compact graph storage and sparse H rows, an empty 100,000-vertex basic
Matcher still retained about 10.3 MiB in `System.index`: a dictionary entry and
empty list for every vertex in `U`. `L_lists` had the same dense-key behavior for
vertices in `A`. The cache equations permit empty rows, and algorithmic readers
already use `.get(vertex, [])`; physically retaining empty mutable lists served
only as an eager directory of the partition.

## Decision

`System.index()` now stores only nonempty Lambda and L rows. `check_lambda()` and
`check_L()` reject keys outside their corresponding partition and recompute each
row against the graph, interpreting a missing key as empty. `check_u()` and
`check_p2()` validate their named graph properties rather than unnecessarily
requiring dense cache keys.

Incremental insertion creates a row when its first member is added. Deletion of
the final member removes that row. Under an active `Systems` journal, the original
map presence, row identity and row contents are retained so rollback resurrects
the exact aliased row or restores the original absence. Unaffected row objects
remain unchanged. Opaque/malformed cache containers still fail validation.

## Evidence

On the same macOS/Python environment, empty 100,000-vertex basic Matcher traced
allocations changed from 18,721,896 retained / 39,423,640 peak bytes (sparse H,
dense System rows) to 7,878,720 retained / 18,972,992 peak bytes (both sparse).
The final fresh process peaked at 40,485,320 bytes RSS. This is one empty-graph
sample, not a production throughput, nonempty workload, or million-vertex claim.
The top remaining traced allocation is the `U` partition set at about 7.2 MiB.

## Verification and limits

Tests compare incremental updates with full cache reconstruction across both
graph backends, require unaffected row identity, check pruning of a final entry,
and inject rollback to verify original row alias/content recovery. Full suite and
property/replay checks remain required because missing-key semantics affect all
basic/multilevel cache readers. `U/A/B` partition storage, edge-dependent rows,
recursive rebuild copies, other state-sized certificates, and durable paper
integration remain separate work.
