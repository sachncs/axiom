# Separate-process offered-load stage

Installed production source `e24ae58`; wheel SHA-256
`e09b81f4bdcffcdab1b3c1c9ae0baeefbc167d0f1e50903461d81234df1d525d`.
Apple M3 Pro / 18 GiB / internal SSD/APFS, macOS 26.7.1, CPython 3.14.8,
SQLite 3.53.4. Sequential fresh isolated installed-wheel processes and archived
runners; no overlapping test/build/performance jobs.
Single-offer runner `ba39b2b`; batch-16 runner `d28d5dd`.

```bash
python -I runner/benchmarks/independent_load.py \
  --database /private/local/path/fresh.db --vertices 1000000 \
  --rate 11000 --query-rate 10000 --seconds 30 \
  --queue-capacity 4096 --ipc-bytes 65536 --ipc-batch 16
```

For the first two records use rate 10000/query-rate 1000/seconds 10/batch 1
and capacities 512/4096. The third uses the command above but batch 1.
Each starts with two million ring edges and performs hot-edge churn; odd admitted
counts leave one edge absent. Every admitted change is real. FULL/fullfsync,
checkpoint interval 32768, retention 16384 and group limit 256 remain enabled.

| Capacity / IPC batch / update-query offers/s | Delivered/s incl. drain | Real acknowledged | Producer misses | IPC drops | Server Busy | Query p99 upper | Ack p99 upper |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 512 / 1 / 10000-1000 | 9603 | 96212 | 70 | 395 | 3323 | 35.2 ms | 154.0 ms |
| 4096 / 1 / 10000-1000 | 9827 | 99714 | 100 | 186 | 0 | 32.5 ms | 203.0 ms |
| 4096 / 1 / 11000-10000 | 10679 | 320569 | 165 | 9266 | 0 | 59.8 ms | 196.1 ms |
| 4096 / 16 / 11000-10000 | **10930** | 329184 | 784 | 32 | 0 | 2.2 ms | 184.8 ms |

All rows pass independent exact topology/proper-maximal matching/recovery and
matching-digest checks. Loss columns count update offers only; raw records also
retain query misses/drops/Busy. The batch-16 run completes 299261 queries,
659 query slots are missed and 80 queries drop at IPC, with no query Busy.
Every original due timestamp survives batching; offered latency includes producer
aggregation, kernel queueing and consumer scheduling, not just lookup compute.
The 30.118-second headline includes final acknowledgment drain.
Owner/producer peak RSS is 182894592/28999680 bytes; ten checkpoints complete.

One-offer transport stalls can magnify query tails and kernel packet overhead.
Batching changes workload delivery, so these are staged samples, not an isolated
native algorithm speedup. No catch-up burst, acknowledgment wait or hidden
unbounded producer queue compensates for misses. Transport buffer sizes and
server capacity are explicit; larger admission trades memory/latency for stall
absorption. There is no production RPC, authentication or external retry protocol.
The first `413680a` runner failed with macOS peer-close reset and yielded no usable
qualification record; `ba39b2b` added drain confirmation/ENOBUFS accounting before
all retained measurements.

User acceptance defers stricter latency engineering for this version. Current
throughput evidence is not hard memory/disk, new-code long-soak or physical
power-loss qualification. [ADR 0019](../../../docs/adrs/0019-independent-arrivals-and-bounded-ipc.md).

The runner now accepts durations up to 1800 seconds for a latest-code 30-minute
soak using the same command with `--seconds 1800`. Histograms, producer packet
buffers and client receipts remain bounded independently of run duration; the
store continues retiring checkpoint/history rows. The extended bound is not
evidence of completed qualification: retain the finished JSON, installed source
and wheel provenance, count all losses, and require exact recovery before
reporting a sustained result. Run on fresh paths without overlapping local tests
or performance jobs. Actual Linux allocation/disk exhaustion is qualified
separately in [ADR 0020](../../../docs/adrs/0020-resource-exhaustion-and-recovery.md).

`--workload sweep` selects constant-space churn through all initial matched ring
edges rather than repeatedly touching `(0,1)`. Each admitted delete/insert pair
uses the same endpoints; rejected/dropped offers never advance that logical trace.
The `Traffic` reference and its `Hot`/`Sweep` strategies independently predict
queries from the committed version. Sweep queries traverse matched endpoints;
hot queries retain vertex zero. Exact final topology accounts for
an odd accepted prefix and recovery compares the full live matching digest.
This widens the working set; it is not a random high-degree/hub workload or evidence
of a completed sweep performance run. The current hot soak uses an archived runner
and is unaffected by these additions.

## Completed 30-minute hot-edge soak

[Raw record](soak-million-4096-11000.json): production wheel and archived runner
source `9b34949`, wheel SHA-256
`1bc2af233ad3cc2b40f467794aba5b007dad12f9a2bdb1f759209c1febd5e463`.
Same declared Mac hardware/storage, fresh isolated installed-wheel process,
1800 seconds, 11000 update/10000 query offers/s, capacity 4096 and IPC batch 16.

19,751,386 real durable updates complete at **10,972.9/s**, including drain;
17,956,015 coherent matching queries and 602 automatic checkpoints complete.
Independent exact topology/proper-maximal matching and exact recovery pass with
the original matching digest. Retained operations are 28,074, native allocation
49,142,880 bytes, owner/producer peak RSS 183,074,816/28,917,760 bytes.

Of 19.8 million update slots, 48,470 are producer-missed and 144 IPC-dropped;
Service Busy is zero. Query misses/drops are 43,537/448 with zero Busy. This is
sustained delivered throughput, **not loss-free delivery**. Acknowledgment p99
upper bound is 178 ms, offered-to-ack p99 178.9 ms, offered-query p99 1.8 ms.
Maxima reach **1.88 seconds ack / 1.74 seconds query**; 153 acknowledgment and
22 query samples exceed the one-second histogram bucket. Do not hide these tails
behind the percentile or claim a maximum-latency SLA.

Sparse OS samples during the second half show approximately 172 MB live owner
RSS, 50.6 MB database and 4 MiB WAL, without growing with operation count in those
samples. Final database size is 50,601,984 bytes. Sampling is not a peak disk bound,
page-cache quota, or proof of indefinite stability. This establishes the latest
production path's scoped sustained hot-edge stage, not full-ring/skew/repeatability,
deployment quotas, network or hardware power-loss qualification.

## Short sweep prefix

[Raw record](sweep-million-4096-11000.json): same installed production wheel,
runner `d6bddb6`, fresh isolated process, 30 seconds at the same offers/capacity.
329,932 real updates complete at 10,972.6/s with 299,959 coherent queries,
ten checkpoints and exact recovery. Update/query misses are 68/41; no IPC drops
or server Busy. Ack/query p99 upper bounds are 182.9 ms/1.9 ms, maxima
208.7 ms/27.0 ms; peak owner RSS is 184.1 MB.

This prefix visits only 164,966 of 500,000 matched edges (329,932 update endpoint
vertices). It is not a complete sweep or a sustained working-set qualification.
A fresh 1800-second sweep uses `--workload sweep` with a distinct database path;
require its completed record and exact recovery before reporting that gate passed.

## Completed 30-minute full-ring sweep

[Raw record](soak-sweep-million-4096-11000.json): same production wheel and
runner `d6bddb6`, fresh isolated process, 1800 seconds with the same offers and
capacity. Production sources in `axiom/` and `native/` are unchanged between wheel
source `9b34949` and `e2202c9`; later additions change the harness/tests/docs.

19,796,515 real durable updates complete at **10,998.0/s**, including drain;
17,997,025 exact version-referenced queries and 603 automatic checkpoints complete.
The trace traverses all 500,000 matched edges nineteen times and queries all
matched endpoints repeatedly. Its odd final prefix leaves exactly one edge absent:
1,999,999 edges, 499,999 matching edges. Independent exact topology/proper-maximal
matching and restart checks reproduce that precise state and its partner digest.

Update misses/drops are 3,421/64; query misses/drops are 2,703/272; no Service
Busy. Ack p99 upper bound is 183.4 ms, offered-to-ack p99 184.2 ms, query p99
1.9 ms; maxima are 238.0 ms / 239.4 ms / 46.9 ms, respectively. No histogram
sample exceeds one second in this run; this does not invalidate the hot soak's
larger tails or establish a maximum-latency guarantee.

Native allocation remains 49,142,880 bytes; owner/producer peak RSS is
182,239,232/29,294,592 bytes. Retained history is 42,707 rows. Sparse samples
show approximately 168 MB live owner RSS, 50.9 MB database and 4 MiB WAL; final
database size is 50,917,376 bytes. These are measured values, not aggregate
deployment quotas. Sustained hot and full-ring stages now pass; broader degree,
growth/drain/skew/burst repeatability and deployment resource qualification remain.

## Explicit denser envelopes

The runner accepts `--width 2`, `8`, or `32` for initial degrees 4, 16, or 64,
and independently checks every expected ring distance, not just edge counts.
Width must remain less than half the vertex universe. `--limit` explicitly sets
both the database-page and checkpoint-image caps (default 64 MiB); `--budget`
sets the shared native allocation budget (default 1 GiB). Reports retain these
settings. Reopen uses the same caps, not a silently smaller recovery policy.

Denser million-vertex images exceed the default 64 MiB snapshot allowance.
Choose and account for explicit limits before running; the harness never grows
them automatically. Database coexistence, WAL, native candidate/undo peaks,
Python/SQLite copies and process headroom all count separately. These options are
not aggregate RSS/filesystem quotas. Small dense exact-recovery and cap-rejection
tests are release gates, not degree-16/64 performance qualification. No denser
million-vertex sustained qualification is claimed. Sequential diagnostics now
retain the following outcomes on fresh paths with no competing local jobs.

### Degree-16 prefix and degree-64 admission rejection

[Degree-16 raw record](dense16-million-4096-11000.json): one million vertices,
eight million initial edges, 30-second sweep prefix with explicit 256 MiB native,
image and database caps. 322,736 real updates complete at 10,751.1/s with 299,847
coherent queries, nine checkpoints and exact recovery. There are 183 update misses
and **7,081 Busy rejections**, no update IPC drops; query misses are 153, no query
Busy/drop. Ack/query p99 upper bounds are 422.7 ms/125.4 ms, maxima
456.8 ms/159.2 ms. Native allocation is 133,142,880 bytes; peak owner RSS 420,708,352
bytes. These tails/caps are not the accepted degree-four version profile.

[Degree-64 rejected stage](dense64-million-rejected.json): construction rejects
with `MemoryError: index growth peak exceeds native budget` under an explicit
1 GiB native cap, before producer start or acknowledgment. There is no throughput
or recovery result. Baseline threshold 32 activates the global directed-edge index
for every degree-64 row. Its 64 million keys require 134,217,728 power-of-two
slots at 16 bytes: **2 GiB of index slots alone**, excluding adjacency/metadata.
This is source-layout arithmetic, not measured RSS. Ring construction already
builds the index once; repeated table growth is not the cause of this minimum.

[Small degree-64 baseline](dense64-baseline-8192.json): 8,192 vertices, five
seconds, explicit 32 MiB native cap, 64 MiB image/database caps. 54,955 real
updates complete at 10,949.8/s with one checkpoint and exact odd-prefix recovery;
native allocation is 20,636,192 bytes and peak owner RSS 67,223,552 bytes. This
baseline permits bounded index-policy comparison without allocating the rejected
million-vertex table. Investigate bounded scans for moderate-degree rows while
retaining indexed hubs; require deterministic matching, rollback, full certificates
and compute/memory measurements before adoption. Do not raise the budget silently
or claim the rejected degree-64 envelope qualified.

### Installed moderate-row policy comparison

[Fixed-trace raw record](index-policy-fixed.json) compares baseline `9b34949`
with candidate `6d5f3cd`, using 18 sequential fresh installed-wheel processes,
three repetitions per binary at each degree, 8,192 vertices and 200,000 real
edits plus partner checks. Wheel hashes and every raw measurement are retained.
All checkpoint and matching hashes agree. These are nondurable core measurements,
not offered-load or service qualification.

At degree 64, native allocation decreases 81.4% (20,621,024 to 3,843,808 bytes),
while median update rate decreases 38.8% (2.862 million to 1.751 million/s).
Degree-four medians are 4.150/4.039 million/s (about 2.7% lower); degree-16
medians are 3.317/3.315 million/s. Native allocation is unchanged for both
controls. The memory saving costs bounded scan work; it is not a free speedup.
The old-binary soaks above must not be transferred to this candidate.

[Million-vertex degree-64 candidate](dense64-candidate-million.json) fits the
same explicit 1 GiB native cap that previously rejected construction. Exact
topology, proper-maximal matching and recovery pass, with six checkpoints,
200,938 real durable updates and 230,013 coherent queries. Native allocation
is 469,142,880 bytes; process peak RSS is 1,345,044,480 bytes, demonstrating why
native budget is not an aggregate memory limit.

The 30-second stage reaches only 6,640.4 updates/s including drain. Update
misses/drops/Busy are 198/76,816/52,048; query misses/drops/Busy are
163/69,824/0. Each p99 exceeds the histogram's one-second range (null is not
zero); maximum ack/offered-ack/query latency is 2.390/2.391/1.510 seconds.
This is a failed denser throughput gate, not evidence that degree 64 meets the
accepted degree-four production envelope. Maintenance and density-sensitive
compute still need profiling and engineering.

[Candidate degree-four release-profile smoke](candidate-sweep-million.json)
uses the same installed wheel sequentially, one million vertices, 128 MiB native
and 64 MiB database/image caps, 30 seconds and 11k/10k offered updates/queries
per second. 329,959 real updates complete at 10,975.4/s including drain, with
299,889 coherent queries, ten checkpoints and independent exact odd-prefix
topology/matching/recovery. Update/query producer misses are 41/111; both streams
have zero IPC drops and zero Busy. Ack/offered-ack/query p99 upper bounds are
185.6/186.4/1.8 ms; maxima are 217.4/218.9/26.5 ms. Native allocation is
49,142,880 bytes; peak owner RSS is 182,501,376 bytes. This passes a short
degree-four stage, not a sustained full-ring sweep or aggregate deployment quota.

[Candidate 30-minute full-ring soak](candidate-soak-sweep-million.json) uses the
same frozen `6d5f3cd` runner/wheel, sequentially after the hub stage, with explicit
128 MiB native and 64 MiB database/image caps. 19,797,233 real durable updates
complete at 10,998.3/s including drain, with 17,996,758 exact version-referenced
queries and 603 checkpoints. Nineteen full update cycles traverse every matched
edge; the odd final prefix has exactly 1,999,999 edges and 499,999 matched edges.
Independent full topology/proper-maximal matching and recovery pass with digest
`9a6fc077996c251f9eb558e01c61afaa9a9edbc86d6a4a26a78f91778db54d28`.

Update misses/drops/Busy are 2,575/192/0; query misses/drops/Busy are
2,042/1,200/0. Ack/offered-ack/query p99 upper bounds are 186.1/186.9/1.9 ms;
maxima are 241.5/242.9/29.6 ms, with no one-second overflow. Native allocation is
49,142,880 bytes; owner/producer peak RSS is 182,026,240/29,212,672 bytes.
Retained history is 43,713 rows. This passes sustained full-ring qualification
for this new binary; it does not transfer the earlier hot soak, qualify degree 64
or growth/drain/bursts, or establish aggregate quotas and maximum-latency SLAs.
The frozen runner predates the exact-deadline rounding fix; its actual offer/loss
counts reconcile exactly. Preserve that provenance rather than rewriting the run.

## Growth/drain qualification trace

`--workload pulse` starts with the configured ring and inserts `vertices / 2`
distinct antipodal chords before deleting them in the same order. A full cycle
contains `vertices` real changes. At one million vertices and width two, the
edge count varies from two to 2.5 million and average degree from four to five.
Partners remain the original perfect matching, so every query has an independent
exact answer at its returned version. Admission sequence, not offer timestamps,
selects the next change: losses never create missing request IDs or no-op updates.
The final reference streams the active chord interval in constant auxiliary space;
native full audit, exact edge membership/count, proper-maximal matching and matching
digest recovery are still mandatory. Run fresh paths and report all loss classes,
maintenance tails and native/process memory separately. This trace is implemented
for qualification; the first measured stage follows.

[First million-vertex growth/drain stage](pulse-million.json): frozen runner
`a500ad4`, installed native/service wheel source `6d5f3cd`, same declared host,
fresh sequential process, explicit 128 MiB native and 64 MiB database/image caps.
Over 120 seconds, 1,319,810 real durable updates complete at 10,996.6/s with
1,199,839 coherent queries and 40 checkpoints. This completes one full million-
update growth/drain cycle, then inserts another 319,810 chords. Final graph:
2,319,810 edges, 500,000 matched edges; exact topology/proper-maximal matching and
recovery pass with the original perfect-matching digest. Update misses/drops/Busy
are 174/16/0; query misses/drops/Busy are 161/0/0.

Ack/offered-ack/query p99 upper bounds are 196.6/197.5/2.8 ms; maxima are
236.2/237.7/33.5 ms, no one-second overflow. Native allocation is 77,130,592
bytes but owner peak RSS reaches **913,391,616 bytes** (producer 29,540,352).
This is a total-memory concern, not a native-cap violation. Throughput/correctness
pass in this scoped stage; total-memory growth/drain qualification is incomplete.
Separate live Python, allocator and RSS diagnostics from rate measurements to
identify the cause; do not describe the larger process peak as already solved.

### Growth/drain residency diagnosis

[Traced samples](pulse-profile.json) and their [disposable sampler](pulse-profile.txt)
separate Python traced bytes, active/reserved malloc statistics and RSS, using the
active macOS SDK's ABI. Python peak is 40,081,723 bytes; sampled RSS reaches
643,874,816 bytes. Tracing changes delivery: only 897,045 updates complete, short
of a full cycle. This is memory diagnosis, not throughput qualification.

The [default repeat](pulse-residency.json) reaches 753,106,944-byte peak RSS;
an [early VM summary](pulse-vmmap-default.txt) shows 111.7 MiB of resident freed
large regions. With only the explicit startup setting `MallocLargeCache=0`, the
[repeat](pulse-nocache.json) completes 1,317,752 updates and 1,197,945 queries,
40 checkpoints and exact full-cycle recovery, reaching 10,979.2 updates/s with
207,519,744-byte peak owner RSS. Native allocation stays 77,130,592 bytes. The
[tuned VM summary](pulse-vmmap-nocache.txt) has no empty-large row. Live accepted
prefixes differ due to counted losses; this is not a fixed-trace CPU comparison.

The tuned repeat's misses/drops/Busy are 232/2,016/0 for updates and 199/1,856/0
for queries. Ack/query p99 upper bounds are 201.1/12.1 ms; maxima are
502.1/496.0 ms. VM inspection can perturb scheduling and tails, so a no-inspection
repeat is required before adopting latency conclusions. This diagnoses a dominant
platform cache contribution, not a hard RSS quota or portable storage redesign.
See [ADR 0022](../../../docs/adrs/0022-allocator-residency.md) for operating boundaries.

`--arrival burst` compresses each second's update quota into its first 250 ms,
giving four times the configured active update rate and a quiet drain interval.
Queries remain steady throughout. Thus `--rate 11000` plans 11,000 updates per
second but offers them at 44,000/s during the active window. All producer misses,
IPC drops and Busy rejections remain explicit, including the final drain. This
schedule is independent of the graph trace (`hot`, `sweep`, or `pulse`); it does
not assert that a bounded owner can admit every burst. No million-vertex burst
qualification result is claimed yet.
