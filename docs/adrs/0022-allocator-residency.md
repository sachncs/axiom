# 0022: Separate allocator residency from native graph allocation budgets

Date: 2026-10-02. Status: macOS large-cache contribution diagnosed; explicit
launch-policy experiment passed; wider resource qualification remains open.

## Context and evidence

The [million-vertex growth/drain stage](../../benchmarks/results/independent/pulse-million.json)
passes scoped throughput and exact recovery but reaches 913,391,616 bytes peak
RSS while final native allocation is only 77,130,592 bytes. A native budget is
not a whole-process limit. Variable-size checkpoint images, SQLite buffers,
Python objects and allocator-retained pages are distinct contributors.

The [instrumented diagnostic](../../benchmarks/results/independent/pulse-profile.json)
records live Python bytes, macOS malloc statistics and RSS every three seconds
with read-only control sequence/generation metadata. Its [disposable sampler](../../benchmarks/results/independent/pulse-profile.txt)
uses the exact `malloc_statistics_t` layout from the active SDK. Python traced
peak is 40,081,723 bytes; sampled RSS reaches 643,874,816 bytes while sampled
malloc in-use/reserved maxima are 179,859,936/210,518,016 bytes. These statistics
do not include every VM category. Tracing changes the workload: only 897,045
updates complete, short of a full cycle, so its rates are not qualification.

A [repeat with a VM inspection](../../benchmarks/results/independent/pulse-residency.json)
still reaches 753,106,944 bytes peak RSS. The [default VM summary](../../benchmarks/results/independent/pulse-vmmap-default.txt)
already shows 111.7 MiB of resident, dirty `MALLOC_LARGE (empty)` regions early
in growth. Freed storage can remain physically resident outside live-allocation
counters. Apple's [allocator initialization](https://github.com/apple-oss-distributions/libmalloc/blob/main/src/malloc.c)
recognizes `MallocLargeCache`; its [large-allocation implementation](https://github.com/apple-oss-distributions/libmalloc/blob/main/src/magazine_large.c)
caches freed large regions when enabled. These sources corroborate the observed
mechanism; they are not a guarantee for every installed OS build.

The [one-knob experiment](../../benchmarks/results/independent/pulse-nocache.json)
sets only `MallocLargeCache=0` before starting the same installed binary, runner
and offered envelope. It completes 1,317,752 real changes at 10,979.2/s, with
1,197,945 coherent queries, 40 checkpoints, a full growth/drain cycle and exact
recovery. Native allocation remains 77,130,592 bytes; owner peak RSS falls to
207,519,744 bytes. The [tuned VM summary](../../benchmarks/results/independent/pulse-vmmap-nocache.txt)
shows no `MALLOC_LARGE (empty)` row. This identifies freed large-region caching
as the dominant residency spike on this host, not a large retained Python graph.
Accepted prefixes differ slightly because arrival losses differ; this is not an
identical fixed-trace CPU comparison. VM inspection can perturb scheduling/tails.

## Decision and boundaries

Keep native budget accounting, ownership, full certificates, exact immutable
checkpoint encoding and SQLite FULL-WAL authority unchanged. Offer an explicit,
operator-selected macOS launch profile disabling large-allocation caching for
the measured growth/drain envelope. Do not modify process-global environment,
re-execute an embedding application's interpreter, or invoke global heap trimming
silently from the library. The setting must exist before process startup; it is
not a Python import-time fix or an aggregate RSS/page-cache quota.

Do not add padding to authoritative images, weaken checksum/rollback guarantees,
or raise native limits to conceal unused allocator residency. Portable segmented
checkpoint I/O or bounded reusable buffers may reduce allocation churn, but they
need their own format/ownership/atomic-publication/failure tests and measured
benefit. A platform-specific launch policy does not deliver that redesign.

The observed peak is not a maximum-memory guarantee. Repeat without VM inspection,
qualify longer growth/drain and bursts, and extend the Linux hard address-space/
filesystem drill to changing density. Deployment aggregate memory/page-cache
quotas, OS/runtime-specific behavior and backup/restore headroom remain separate.
No change to hardware power-loss deferral or the failing degree-64 throughput gate.
