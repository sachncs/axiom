# 0023: Integrate paper algorithms into durable production

Date: 2026-10-03. Status: required by user; **not implemented**.

## Context

The user rejects a permanent split where only the native matcher is durable and
the paper basic/multilevel engines are nondurable research destinations. Earlier
approval of an independent native algorithm did not require abandoning the paper.
The current SQLite formats and Service implementation select native Engine only.

## Required direction

The only supported matching methods are **`basic`** and **`multilevel`**. The
paper `Matcher` is the production matching algorithm; `basic` is the default and
replaces the separate native matching algorithm. `multilevel` selects the paper
hierarchy. The native `Packed` container may remain as an implementation of the
graph-storage contract because compact mutable storage is a separate concern
from matching policy. The native `Engine` matching algorithm must not remain a
third selectable production method or be relabeled as either paper method.

Bring both paper methods through the same durable Service boundary, with a
shared lifecycle contract and mode-specific implementations for mutation,
validation, publication, rollback and recovery. Persist algorithm identity and
construction parameters. Opening a store with incompatible parameters must
reject, never reinterpret its history. New production stores default to `basic`;
selecting `multilevel` is explicit. Existing native-format stores must remain
readable only under an explicit compatibility/migration policy, never silently
open as Basic or Multilevel. The user has since rejected backward compatibility
shims: do not retain a native matching backend, native database reader, or
migration-only native service mode. Replace the old native durable format
outright; old stores are unsupported and must be clearly rejected, not silently
reinterpreted.

Paper recovery must reproduce the exact accepted graph, matching,
coloring/fans, hierarchy and accounting—not merely any valid matching with the
same size. Reject invalid/unsupported state explicitly. The durable Service
contract must retain commit-before-ack, bounded history, same-ID retries,
failure isolation, coherent reads, backup and exact reopen. The old native
engine and its durable compatibility reader are not part of the target product.
Compact `Packed` graph storage remains allowed because it is a storage primitive,
not a matching algorithm.

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

This is a backend replacement, not a mode rename. Current `Durable`/`Service`
are coupled to `Engine` transactions, checkpoint images, recovery, and queries;
paper `Matcher` currently provides per-update rollback but not a durable
multi-update transaction or a versioned exact checkpoint codec. The former
native database format will not be carried forward; a format change must reject
old stores with a direct unsupported-format error. Hardware power-loss and
billion-vertex qualification remain deferred. The paper’s complete theoretical
bound is still not established. Shared production durability does not transfer
a theorem or a 10k-throughput result between Basic and Multilevel.
