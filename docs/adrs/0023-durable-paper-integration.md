# 0023: Integrate paper algorithms into durable production

Date: 2026-10-03. Status: **implementation underway; independent qualification pending**.

## Context

The user rejected a permanent split where only the native matcher is durable
and the paper Basic/Multilevel algorithms are nondurable research destinations.
The native matching implementation and its compatibility path are now removed
from the product. Durable/Service select a paper mode; broad qualification is
still required.

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
read or migrate native-format stores. No native compatibility reader, matcher,
or migration-only service mode remains. Old stores are unsupported and must fail
closed with a direct format error, never silently open as Basic or Multilevel.

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

The implementation records the selected paper mode in store metadata and
persists each Durable request group in one SQLite transaction. To bound retained
paper undo, Matcher updates start in private slices of at most eight operations
under the exclusive Durable owner. A journal-capacity failure causes the owner
to replay the committed prefix and retry the whole group with half-sized slices,
down to one operation. Only after all slices pass does SQLite commit the
complete group. No Durable or Service read can observe intermediate slices. If
a later slice fails before persistence, the owner reconstructs the previously
committed state by replaying and auditing its operation prefix. Both modes have
tests for failures after an earlier slice, adaptive capacity retry, and exact
graph/matching state across batch partitions and reopen. A single operation
that exceeds a component's own hard journal cap still fails atomically. This does not
remove all remaining graph-sized paper-state work or establish every storage,
package, deployment, or workload qualification. The former native format is
intentionally unsupported and fails closed; no compatibility shim remains.

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

This is a backend replacement, not a mode rename. Multi-update atomicity and
deterministic operation-log replay now share one Durable/Service boundary for
both modes. Recovery remains linear in the configured operation-history limit;
no compact paper-state codec or log compaction exists. A one-million-vertex,
average-degree-four Basic smoke trace with 256-operation groups passed exact
recovery at about 506 durable real updates/s and about 1.54 GB process peak RSS.
A 128k Multilevel smoke trace passed exact recovery at about 49 updates/s,
657 ms ack p99, and 322 MB process peak RSS. Both are short, non-repeatable
smoke checks, and neither approaches the 10k/s target; they expose a major
throughput and memory gap, especially for Multilevel. The Multilevel throughput
figure is the pre-ADR-0103 baseline and has since been superseded by a one-off
3,136 updates/s, batch-256 million-vertex smoke; the newer result remains below
target and is not a repeatable qualification. The Basic figure remains the
latest recorded million-vertex Basic smoke. Remaining gates include
repeatability/skew/adversarial testing, memory reduction, recovery-time limits,
installed deployment checks, and sustained throughput. Hardware power-loss and
billion-vertex qualification remain deferred. The paper’s complete theoretical
bound is still not established; no result transfers between Basic and
Multilevel.
