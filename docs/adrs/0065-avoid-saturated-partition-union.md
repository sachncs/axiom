# ADR 0065: Avoid materializing the saturated partition union

Date: 2026-10-03  
State: Implemented; refinement-level qualification remains open

## Context

Hierarchy refinement built `previous.A | previous.B` as a mutable Python set and
retained it as the `settled` membership index while promoting vertices from U.
Dense `Vertices` operands implement union by converting members to a Python set,
so the temporary could consume tens of bytes per settled vertex. The algorithm
only needs membership checks and records newly promoted vertices in the
destination A/B partitions anyway.

## Decision

During the initial previous-B classification, query `previous.A` and
`previous.B` directly. After that pass, every vertex in old B belongs to either
`new_a` or `new_b`; each promoted old-U vertex is also inserted in one of those
destination partitions before the next promotion. Thus the settled predicate
during promotion is `previous.A OR new_a OR new_b`. Remove the materialized
`old_s` union and the separate mutable `settled` set.

## Correctness argument

At the start of the first pass, settled is exactly old A union old B. The
predicate `v in previous.A or v in previous.B` is equivalent for every neighbor.
After the first pass, new A and new B partition old B. Each promotion removes one
vertex from new U and places it in new A or new B. Therefore, at every subsequent
promotion, `previous.A ∪ new_a ∪ new_b` is exactly old A ∪ old B plus all earlier
promoted vertices, which is the old `settled` value. Other code does not observe
the removed union root.

## Evidence and limits

- Five alternating untraced repeats on a million-label probe with two disjoint
  500,000-member `Vertices` partitions measured median set-union-plus-one-million
  queries at 0.0422 s and direct source-partition membership at 0.13272 s. Direct
  membership is about 3.1× slower for that query shape, so this is an explicit
  memory/compute tradeoff, not a throughput improvement.
- A separate traced union sample peaked at 87,230,568 bytes. Direct membership
  avoids retaining/materializing that Python union but pays the extra partition
  lookups.
- Three traced full-refinement repeats on a 2,048-vertex degree-four `Packed`
  ring produced identical hierarchy-state digests and passed `Hierarchy.check()`
  for the old and candidate paths. Median traced peak fell from 3,434,623 to
  2,680,767 bytes (22.0%); median traced time was 1.614 s old and 1.633 s new,
  within the resolution of this small sample. This includes streaming/copy
  changes from ADRs 0063–0064 as well as the partition-union change, so it is not
  an isolated attribution or large-scale qualification.
- A refinement regression patches `Vertices.__or__` to fail while refining a
  valid hierarchy with dense compact A/B roots; the refinement still passes its
  full independent hierarchy certificate.
- Broader workload and peak-RSS qualification remains open.

See the [raw measurement](../benchmarks/results/paper/saturated-union-membership.json).

## Alternatives

- Retain `A ∪ B` as a Python set: rejected for this memory-sensitive refinement
  path because it peaks at 87.2 MB for the measured million-label shape. The
  alternative uses more membership CPU; this tradeoff must be revisited if full
  refinement latency regresses materially.
- Build a second dense compact union: rejected because it still scans/copies the
  partition and requires additional universe-sized arrays.
- Mutate the inherited partition roots: rejected because parent hierarchy state
  must remain unchanged after refinement and failure.

## Follow-up

Measure full hierarchy refinement peak RSS and rate across sparse/dense A/B
shapes, promotion counts, and failed candidate publication. Audit remaining
multi-source A/N/R union construction separately; do not generalize this local
microbenchmark or 2,048-vertex sample to the complete engine.
