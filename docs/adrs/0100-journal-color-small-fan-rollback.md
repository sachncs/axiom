# 0100: Journal Color-Small fan rollback

Date: 2026-10-04. State: implemented; operation-level rollback allocation probe
only. Color-Small entry/exit audits remain global.

## Context

`Construction.small` retained `tuple(fans)` before activation so an exception
could clear the fan collection and rebuild every fan. `Fans.__iter__` sorts all
members, so even a failure after changing one or two fans paid O(F log F) time and
O(F) temporary storage for F unrelated fans.

## Decision

Add an owner-bound `FanJournal` that records each fan's original membership only
on its first add, discard, or update. Nested journals propagate first-write
before-images to their parent. Root-replacing relabel records the existing index
roots and membership deltas so rollback can restore root identity before
replaying touched entries. `Construction.small` now commits this journal on
success and rolls it back on failure instead of copying/rebuilding the complete
fan collection. The `Witness` schema includes the inactive journal slot.

## Evidence and limits

An injected second-activation failure rejects whole-fan iteration during the
transaction and then compares complete `Witness` state, coloring, and fan-root
identities. A nested rollback test combines an update, relabel, nested commit,
and insertion, then verifies the exact original state and roots. In a 20,000-fan
fixture with one touched fan, seven repeats measured the old sorted tuple
snapshot at 1,776,160 traced peak bytes and 8.24 ms median; a discard plus
first-write journal rollback used 1,872 bytes and 0.017 ms. This isolates
rollback preparation/application and is not full Color-Small throughput.

Color-Small still performs full coloring/fan validation at its transaction
boundary; this ADR removes the full fan before-image but does not remove those
global scans or other fan/pruning snapshots.
