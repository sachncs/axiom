# ADR 0019: Qualify independent arrivals with bounded transport accounting

Date: 2026-10-02. Status: implemented/tested; million-vertex throughput stage
measured; hard resource/recovery qualification remains open.

## Context and decision

The in-process producer shares the service GIL and misses thousands of update
slots. Separate arrival generation into a spawned process, retaining the same
no-catch-up schedule. Send timestamped offers over bounded nonblocking local
datagrams; separately reconcile producer misses, IPC drops, server Busy, actual
durable acknowledgments and query outcomes. Neither offered rate nor queue
acceptance counts as throughput.

One consumer constructs contiguous IDs only when admission succeeds and invokes
the real individual Service API. Offers request hot-edge churn; they are not
remote sequenced Request payloads or a production RPC protocol. Every admitted
operation is a real insert/delete, FULL/fullfsync and native checkpoints remain
enabled, queries check exact versioned partners, and recovery independently
checks full topology/proper-maximal matching and exact partner digest.

Optional transport batching holds at most 64 offers per producer thread (576
payload bytes), not an unbounded queue. Default is one; the measured batch of 16
keeps each timestamp and includes aggregation/IPC delay in offered latency.
At lower arrival rates aggregation may take much longer; this is not a timer-
bounded flush SLA. Final partial batches flush. Entire rejected datagrams count
all their offers as IPC drops, including macOS ENOBUFS.
The producer sends fixed terminal counters then awaits explicit drain confirmation
before closing its socket; otherwise macOS can reset the receiving socketpair.
Deadlines and failure cleanup bound producer lifetime and admitted work.

## Evidence and operational consequence

At one million vertices, separate single-offer IPC with capacity 512 delivers
9603/s and rejects 3323 update offers. Capacity 4096 eliminates server Busy but
still delivers 9827/s at 10k scheduled offers, including drain and transport loss.
One 30-second 11k-update/10k-query-offer run with capacity 4096 and batch 16
delivers **10930 real durable updates/s**, 329184 changes and 299261 coherent
queries, ten native checkpoints and exact recovery. Query p99 <=2.2 ms,
max 28.1 ms; acknowledgment p99 <=184.8 ms, max 215.3 ms. There remain 784 missed
update slots and 32 IPC-dropped updates; no server Busy. These are not loss-free
arrival or worst-case latency promises.

Use explicitly configured capacity 4096 for this envelope; the Service default
is unchanged. Larger bounded admission absorbs checkpoint stalls but increases
retained receipts and latency exposure. Owner/producer peak RSS is observed at
182.9/29.0 MB, not an enforced process ceiling. Single short samples and a local
transport cannot establish a network SLA, hard RSS/disk bounds or power-loss safety.
[Raw artifacts and commands](../../benchmarks/results/independent/README.md).

The user accepted current latency as good enough for this version on 2026-10-02
and requested tighter latency engineering be deferred. Do not invent numeric
latency/RSS SLAs from that acceptance. Retain maintenance-tail measurements and
make stricter query/ack latency, timer-bounded IPC flush and background consistent
checkpoint design future engineering work. Continue with hard resource failure
behavior and backup/recovery validation; this acceptance is not a power-loss claim.

The subsequent installed-wheel 30-minute hot-edge soak completes 19,751,386 real
durable updates at 10,972.9/s, 17,956,015 coherent queries and 602 checkpoints,
with exact independent recovery. Ack/query p99 upper bounds are 178 ms/1.8 ms;
maxima are 1.88 s/1.74 s. Explicit update misses/drops are 48,470/144, no Busy.
Peak owner RSS is 183.1 MB; sampled database/WAL sizes remain around 50.6 MB/4 MiB.
See the raw artifact/provenance above. This passes the scoped latest production
path sustained stage, not full-ring/repeatability or deployment resource quotas.
Actual Linux memory/disk exhaustion is a separate passed stage (ADR 0020).
Hardware power-loss qualification was explicitly deferred by the user for this
version; it remains unclaimed future engineering.
