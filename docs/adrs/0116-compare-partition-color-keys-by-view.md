# ADR 0116: Compare partition coloring keys by view

Date: 2026-10-04
State: Implemented; rebuild allocation impact not yet measured

## Context

`Matcher.partition()` validates a colorer result against the current system
matching. It previously converted both the coloring mapping and system matching
to new sets on every successful partition, duplicating O(|M|) references before
it allocated the partition classes themselves.

## Decision

Compare the mapping's set-like `keys()` view directly with the system matching.
Only on mismatch, construct the missing/extra diagnostic sets from the key view
and matching. Preserve the existing incomplete-coloring error and retain the
independent range/properness checks while assigning classes.

## Consequences

Successful partitions avoid two temporary O(|M|) sets. The color mapping,
matching, and resulting color classes are still retained as required. Failure
diagnostics remain detailed but may allocate proportional to the mismatched
inputs. No update throughput or rebuild-time claim is made.

## Verification

A key-view-only mapping rejects iteration but supports `items()` and set-like
key comparison; `Matcher.partition()` still produces the expected complete
classes. The out-of-range-color regression and full paper/rebuild suite remain
the correctness gates.
