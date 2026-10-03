# 0039: Keep empty auxiliary H rows implicit

Date: 2026-10-03. Status: implemented; broader paper-engine scaling remains active.

## Context

An empty 100,000-vertex basic `Matcher` profile retained about 20.6 MiB in
`core.py` at the H-row set construction site: one empty Python set for each
unmatched vertex. H is a directed edge index, not a partition table. An empty
outgoing row contains no edge and every algorithmic query can treat a missing
key as empty. Retaining those sets duplicated graph-universe state unnecessarily.

## Decision

`Matcher` materializes an H row only when the source has at least one live H
target. Rebuild allocates a target set lazily on the first edge. Incremental
`ProcUpdate` removes the old row and leaves it absent when the replacement is
empty. Reverse rows remain sparse and are removed when their last source leaves.
The independent auxiliary-index certificate derives the same sparse canonical
representation. Public neighbor semantics are unchanged: absent H keys mean no
outgoing H edges; callers should use `H.get(vertex, set())` for lookup.

## Evidence

On the same macOS/Python host, empty 100,000-vertex basic Matcher construction
with `Packed` measured 62,833,120 bytes peak RSS after the change. A separate
same-size `Adjacency` run measured 98,959,864 bytes. Tracemalloc for the compact
run retained 18,721,896 bytes and peaked at 39,423,640 bytes; before sparse H,
the same diagnostic retained 45,562,448 bytes and peaked at 72,405,648 bytes.
The observed retained and peak traced reductions are about 59% and 46% for this
single empty-graph Matcher sample. These are diagnostics, not repeated workload
qualification or a projection to one million vertices.

## Verification and limits

Tests require empty basic/multilevel H indexes to stay empty, compare the index
against authoritative graph/cache state after randomized updates, and retain
rollback/replay checks. This removes empty H-row overhead only; U membership,
System lambda-cache rows, Python algorithm state, graph edges, durable state and
per-mode throughput remain separate costs.
