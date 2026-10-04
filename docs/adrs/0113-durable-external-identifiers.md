# ADR 0113: Persist typed external identifiers in the durable owner

Date: 2026-10-04
State: Accepted; implementation and qualification in progress

## Context

The paper matcher uses dense integer slots in a fixed vertex universe, while
applications commonly address vertices by strings, integers, or UUIDs. Keeping
that mapping only in a process would make restart, retries, and query results
ambiguous. Reusing a slot after deletion would also risk assigning an old
request or backup to a different logical vertex.

## Decision

Persist an exact typed identifier codec and an immutable mapping in SQLite.
Integer, string, and UUID namespaces are disjoint. Each newly registered
identifier takes the next slot; registration is idempotent, mappings are never
removed or reused, and the existing fixed `n` capacity remains authoritative.
The allocation cursor and mapping row commit in one SQLite transaction. Each
mapping has a digest checked during lookup and recovery. Durable format v2
retains a transactional migration from the verified v1 operation log and
rehashes its chain under the new metadata root.

The local Service serializes registration, update, and read operations through
its owner. External-ID update batches still use the same atomic durable batch
path; their sequences and payloads participate in normal retry validation.
Unknown identifiers are rejected without fail-stopping a healthy Service.

## Boundaries

This adds durable identities, not dynamic graph growth or vertex deletion.
Slots are finite and registration fails at `n`; a registered slot is permanent.
It does not change the matching algorithm, establish 10k updates/s, or close any
release qualification gate. SQLite remains the durable authority; `Packed`
remains graph storage. No legacy native matcher or database compatibility shim
is introduced.

## Verification required

Test canonical/type-separated encoding; duplicate and full-capacity
registration; SQLite-trigger rollback; malformed/corrupt mapping recovery;
v1 migration rollback and successful replay; external update/query/reopen for
both paper modes; batch retry and exact rollback; and concurrent Service
registration/update/read ordering. Then run the complete suite, static checks,
and independent per-mode qualification. Until those pass, this ADR records the
selected design, not a production-readiness claim.
