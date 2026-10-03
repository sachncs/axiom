# 0037: Journal built-in adjacency edits by touched edge

Date: 2026-10-03. Status: implemented; full paper qualification remains active.

## Context

`Matcher` already retained Python object roots and journaled its mutable indexes,
but its default `Adjacency` graph still had two whole-graph costs on each edit:
the transaction copied every managed graph's complete edge set for rollback,
and the mutation certificate compared complete before/after edge sets. Both costs
grew with graph size even when one edge changed. Recursive `deepcopy` had been
removed, but that did not make the ordinary Python graph transaction local.

## Decision

The built-in `Adjacency` graph now supports one owner-bound `begin`/`commit`/
`rollback` edge journal. Each successful insertion or deletion records its
canonical edge and direction. Rollback visits only recorded edits, preserving the
identity of the adjacency rows and graph object. Adds remove a partial edit if
either endpoint-set mutation raises. Matcher treats only the exact built-in class
as journal-capable; custom subclasses and opaque graph implementations retain the
previous defensive full-edge certificate and rollback fallback.

For built-in `Adjacency`, Matcher certifies the changed edge, endpoint degrees,
and cached edge count locally. It starts journals for every managed built-in
adjacency graph and rolls them back in reverse order on failure. Native `Packed`
transactions and their joint publication function are unchanged. `Witness`
encodes only logical graph state, not ephemeral journal tokens.

## Consequences and limits

- Ordinary built-in graph rollback bookkeeping is O(k) in the number of edge
  edits made by the transition, not O(m) in the number of live graph edges.
- The local mutation certificate is O(1) for each edited edge.
- This is an undo journal, not a durable format or a graph storage redesign; the
  default Python adjacency still has its per-vertex set memory cost.
- Rollback of a deleted edge can need Python set allocation. If rollback itself
  fails, Matcher already enters fail-stop rather than claiming the graph is safe.
- Full-state `Witness` tests stay state-sized by design. Opaque custom graphs,
  phase snapshot construction, some admission/certificate paths, and durable
  basic/multilevel integration remain open engineering work.

## Verification

Tests cover exact mixed-edit rollback, stale/nested token rejection, no whole-edge
iteration during a built-in local update, and Matcher failure/retry across both
paper modes and storage backends. These tests establish the implementation
contract, not a broad throughput claim.
