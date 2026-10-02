# 0023: Integrate paper algorithms into durable production

Date: 2026-10-03. Status: required by user; **not implemented**.

## Context

The user rejects a permanent split where only the native matcher is durable and
the paper basic/multilevel engines are nondurable research destinations. Earlier
approval of an independent native algorithm did not require abandoning the paper.
The current SQLite formats and Service implementation select native Engine only.

## Required direction

Provide basic, multilevel and native algorithms through a common durable service
boundary, with explicit selection rather than silently substituting algorithms.
Use polymorphic backend contracts for mutation, validation, publication, rollback
and recovery. Persist algorithm identity and construction parameters. Opening a
store with incompatible parameters must reject, never reinterpret its history.

Preserve the existing native format and receipts. Paper recovery must reproduce
the exact accepted graph, matching, coloring/fans, hierarchy and accounting—not
merely any valid matching with the same size. Reject invalid/unsupported state
explicitly. The storage contract must retain commit-before-ack, bounded history,
same-ID retries, failure isolation, coherent reads, backup and exact reopen.

Complete the paper mutation-journal inventory before replacing its snapshot oracle.
A graph-only undo log cannot restore fan/coloring/hierarchy state. Journals must
cover all coupled mutations and preserve aliases and graph/object identity. Keep
differential snapshot checks until failure injection demonstrates equivalence.

## Verification gates

Implemented prerequisite: the bounded full-state `Witness` diagnostic compares
paper replay prefixes and failure rollback, including aliases and redundant
indexes. See the [state inventory and exclusions](../paper-state.md). It has no
decoder and does not make paper modes durable or remove their snapshots.

- Both paper modes through the same admission/query/update/reopen workflow.
- Failure before repair, during fan collisions/chain flips, hierarchy rebuilds,
  persistence and publication; exact full-state rollback or explicit fail-stop.
- Deterministic recovery, retained/expired retries, incompatible mode refusal,
  corrupt histories, backups, concurrent clients and overload.
- Installed-artifact tests, resource bounds and independent per-mode throughput,
  memory and latency evidence. Native performance is not paper performance.

## Rejected shortcuts

Do not relabel the native algorithm as a paper implementation, pickle arbitrary
objects as a production codec, introduce an unbounded replay history, recompute
an arbitrary matching on reopen, or claim durability from in-process rollback.
Do not remove truthful current limitations from docs before implementation.

## Consequences

This expands active engineering scope; hardware power-loss and billion-vertex
qualification remain deferred. The paper’s complete theoretical bound is still
not established. Shared production durability does not transfer a theorem or a
10k-throughput result between different algorithms.
