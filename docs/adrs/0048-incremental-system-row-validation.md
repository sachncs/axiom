# ADR 0048: Incremental System cache-row validation

Date: 2026-10-03

## Context

After ADR 0047, a 512-vertex multilevel cProfile showed `Systems.__init__` and
`Systems.validate` still walking every `Lambda` and `L` cache row on every
transaction. Stable Matcher-owned Systems had already been admitted, and their
cache mutations go through the first-write `Systems` journal. Repeating a
whole-map structural scan duplicated that established ownership boundary.

## Decision

- Keep standalone `Systems` construction exhaustive by default (`audit=True`):
  every existing cache row is checked before journal handles bind.
- In the Matcher atomic-update owner, use `audit=False` only for the already
  admitted stable System roots. Admission checks top-level record/schema,
  partition and cache-map types without traversing row values.
- At commit, validate each journal-touched cache row for a nonempty sorted list
  of distinct in-range non-self vertex labels. Missing rows are valid only when
  the cache delta removed their final element.
- Any new System root or replaced `lambda_lists`/`L_lists` map receives a full
  row audit before publication. Explicit caller use of the standalone journal
  retains the exhaustive default.
- Generated update tests run full `check_lambda()`/`check_L()` cache equality
  audits after every operation; existing
  tests continue checking malformed standalone admission, candidates, alias
  restoration, capacity failure, thread misuse and exact rollback.

The fast path relies on the Matcher single-owner contract: mutations during an
update are made through the admitted journal. Direct out-of-band edits to a
Matcher-owned System between updates are not covered by that local proof;
callers should use Matcher operations and explicit `System.check()` when
inspecting or editing standalone System objects. Full validation at rebuild
boundaries and in test oracles remains mandatory.

## Alternatives considered

- Retain whole-map scans for every update: correct but repeatedly traverses
  unrelated rows and allocates/scans row iterators.
- Trust arbitrary new/replaced Systems: rejected; candidates and changed cache
  map roots retain complete row validation.
- Sample cache rows: rejected because malformed touched rows could corrupt
  `ProcUpdate`/rematching behavior.
- Persist a Python-side fingerprint table for every cache row: rejected for now
  because it adds retained memory and another mutation-maintenance invariant.

## Evidence

[`system-certificates.json`](../../benchmarks/results/paper/system-certificates.json)
records baseline `c3d443a` and the candidate on a fixed 8,192-vertex sparse
average-degree-four multilevel churn trace (seed 42, 128 real updates, five
batches). Rate rises from 436.54 to 610.30 updates/s (1.40×), with identical
final graph/matching certificate hashes and repair/rebuild counters. A separate
512-vertex, 128-update cProfile falls from 0.1035 to 0.0733 seconds (29.2%).
Measured traced allocations and process RSS are effectively unchanged. These
are bounded diagnostics, not durable or million-vertex qualification.

The full suite passes 1,218 tests; generated traces also run full cache-row
equality oracles after each operation. The entire `System.check()` is not a
valid every-update oracle because phase-owned degree bounds intentionally need
not hold against the live graph between rebuilds. Ruff and mypy pass.

## Consequences

Ordinary updates validate only touched cache rows; rebuild candidates remain
fully audited. This reduces repeated compute but does not improve retained
storage. The next profiled costs are stale matching cleanup, graph lookups,
transaction entry/exit and remaining row-level auxiliary certificates. The
Historical status note (2026-10-04): the paper Basic and Multilevel modes are now
integrated into the SQLite-backed Durable/Service path by ADR 0023. This ADR's
System-row validation decision remains in force; older wording about paper-mode
durability and integration is superseded.
