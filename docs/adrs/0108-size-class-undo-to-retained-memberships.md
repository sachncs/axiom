# ADR 0108: Size class undo to retained memberships

- Status: implemented; original million-vertex failure trace not reproduced
- Date: 2026-10-04

## Context

`Classes` originally charged distinct class/seed root references and changed
membership before-images to one fixed 65,536-cell limit. A large retained
coloring therefore had fewer undo cells available, and Durable's chunk-halving
could not help a single delete whose class repair exceeded the remaining room.

## Decision

When no explicit test/owner limit is supplied, calculate the class journal
ceiling as the greater of 65,536 and the number of distinct retained roots plus
the number of memberships currently held by those roots. Repeated aliases count
once. Each original `(root, edge)` membership can be recorded at most once, so
this is a finite, exact upper bound for all class before-images that this
transaction can require. Continue allocating records only on the first actual
removal, and restore original sets, slots, and aliases in place on rollback.
Explicit capacities retain their existing strict behavior for focused
capacity/admission tests.

## Consequences

- Root count no longer consumes the undo-cell allowance.
- Valid class deletion/repair cannot exhaust the class journal merely because
  its retained coloring exceeds 65,536 memberships.
- Peak temporary memory remains proportional to the actual class write set;
  the ceiling itself does not preallocate the undo records.
- Durable chunk retries remain necessary for the independently bounded view,
  auxiliary, system, hierarchy, and clock journals.
- This removes a class-specific artificial ceiling, not all resource limits.
  Other component caps still reject an intrinsically oversized single update.

## Evidence and remaining qualification

The regression removes 65,537 original class memberships and verifies exact
in-place rollback, including set/list roots and seed sharing. The broader
Durable suite drives a real `Classes.remove` admission failure in both Basic and
Multilevel, retries it with smaller private chunks, and verifies one contiguous
history after reopen. A separate regression fails the second chunk after the
first chunk has completed, then checks exact in-memory Witness, public state,
history and SQLite control/operation rows before retrying and reopening. These
tests verify both capacity retry and cross-chunk rollback; the injected failure
does not claim that production capacity was exhausted.

A bounded regression also admits 65,537 distinct roots (mostly empty), removes
a real seed membership, and verifies root identity and exact rollback. This
covers the large-root admission boundary without constructing a huge matcher.
The report that prompted this review included no retained database or exception
details, so the exact failing trace remains unavailable.

A one-million-vertex, average-degree-four FULL-WAL smoke completed in both
methods with 32 real changes, 16 partner queries, independent graph/matching
audit and exact replay. Peak RSS was 1.42 GiB Basic and 2.12 GiB Multilevel.
This short smoke exercises deletes on the production-sized coloring, but is not
the original reported trace, does not induce class-journal exhaustion, and is
not throughput or resource-limit qualification. The large membership fixture
proves the former fixed class threshold is gone, not that every single update
fits a particular memory budget. Views, Systems, hierarchy, auxiliary and clock
journals retain their own capacity policies and failure paths.

On 2026-10-04, the checked-in durable harness was additionally run at one
million vertices / two million edges with seed 599, 128 churn pairs and one
256-operation group. Both modes passed independent audit, retry verification,
and exact reopen recovery. One run measured 2,198 updates/s and 1.61 GB peak RSS
for Basic, and 8,048 updates/s and 2.07 GB peak RSS for Multilevel. A separate
32-update run also passed in both modes. Neither run reproduced the reported
class-journal exhaustion; these short runs are smoke evidence, not qualification
or proof against the unavailable original trace.
