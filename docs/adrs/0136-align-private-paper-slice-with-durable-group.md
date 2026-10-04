# ADR 0136: Align private paper slices with durable groups

- Status: implemented; million-vertex qualification pending
- Date: 2026-10-04

## Context

The telemetry-enabled one-million-vertex Basic worker acknowledged only
200,192 of 1,040,000 operations in 240.985 seconds before its 300-second
deadline. Service grouped the submitted 256-request bursts; the durable update
loop, not the verifier, was the measured bottleneck. `Durable.apply()` nevertheless
opened/validated/committed a separate Matcher transaction every eight requests,
repeating journal setup 32 times inside a typical caller group.

A controlled local microbenchmark used a 10,000-vertex degree-four graph,
10,000 real durable updates, batches of 256, fresh SQLite state, and a final
durable audit. It swept private slice sizes 8, 16, 32, 64, 128, and 256. All
configurations completed without journal-capacity retries:

| Private slice | Basic updates/s | Multilevel updates/s |
| ---: | ---: | ---: |
| 8 | 11,443 | 7,277 |
| 16 | 13,497 | 7,537 |
| 32 | 14,797 | 7,916 |
| 64 | 15,659 | 8,281 |
| 128 | 16,249 | 8,666 |
| 256 | 16,669 | 9,248 |

This is directional component evidence, not a million-vertex or Service
qualification. A separate Service experiment confirmed bursts of 256
individual requests coalesce into groups of 256; explicit `submit_batch` did
not materially alter those 10,000-vertex rates.

## Decision

Set the initial private `PAPER_CHUNK` to 256, matching the default bounded
Durable/Service caller group. Continue to treat journal capacity as data
dependent: on `JournalCapacityError`, discard/replay the entire uncommitted
caller group and retry with half-sized private slices. Do not widen the
qualification deadline. Tests that specifically verify small-slice replay
continue to set the private chunk to eight; new tests exercise default-sized
multi-slice rollback and capacity halving.

## Consequences

- A normal 256-operation durable group needs one Matcher transaction rather
  than 32, reducing repeated journal and validation setup.
- Larger repair bursts can exceed component-specific limits; exact whole-group
  rollback and adaptive replay remain mandatory.
- Startup history replay also begins with 256-operation slices and retains the
  same halving behavior on component capacity pressure.
- 10k/s at one million vertices remains unqualified. The next hosted run must
  show its update progress, group sizes, memory use, and exact recovery under
  the existing 512 MiB / 300-second limits.

## Verification

The full local suite passes with `PAPER_CHUNK=256` (1,276 passed, one optional
performance-report test skipped because `matplotlib` is unavailable). Focused
rollback/capacity tests prove a failure after a completed private slice restores
the caller group and that a simulated capacity failure at the 256 boundary
replays with 128-sized slices. Ruff, mypy, and format checks pass. The local
sweep is not production or resource qualification; hosted constrained Basic
and Multilevel runs remain open.
