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
million-vertex measurement has completed yet; run only after the current sweep
finishes, on fresh paths with no competing local jobs.
