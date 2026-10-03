# ADR 0015: Expose skew, saturation and producer losses in qualification

Date: 2026-10-02. Status: deterministic skew and paced offered-load benchmarks
implemented/tested; broad sustained/resource qualification pending.

## Context and decision

Closed-loop windows reduce arrival rate when service slows. Uniform fixed-degree
traces do not expose high-degree matching repair. Average degree alone does not
bound the worst vertex or per-update compute. A faster lookup or passing short
throughput run is not enough to qualify a reliable product.

`benchmarks/service.py --hub-degree D` builds a known degree-D hub, then repeatedly
deletes its matched edge and inserts/removes an alternate chord. The other hub
neighbors are matched, so deletion must search for free neighbors rather than
merely choosing the first neighbor. Every timed update is real. Bootstrap counts
and time are separate; logical request IDs include that committed prefix.
Audit the complete ring-plus-hub topology, maximal matching and exact recovered
partner digest. Count the altered edge/degree envelope explicitly, not as an
unchanged degree-four graph. Limit D to 262144 and use bounded setup groups;
setup errors close the owner before reporting failure.

`benchmarks/overload.py` offers hot-edge changes on a paced clock without waiting
for acknowledgments. Pending receipts are bounded; full admission counts explicit
`BusyError` and does not consume an update ID. Count scheduled, missed, rejected,
accepted and acknowledged work separately and require their exact reconciliation.
Late producers skip/count overdue slots rather than generating an unbounded
catch-up burst. Report observed acknowledgment latency and intended-arrival-to-ack
latency; include final drain in delivered throughput. A separately paced query
thread validates exact coupled committed versions/partners of the hot endpoint.
Capture live versioned matching pages, then independently recover/audit topology,
proper maximal matching and the same digest outside headline timing.

The separate-process runner now offers `--workload pulse` through polymorphic
`Traffic` implementations. Its deterministic cycle inserts one antipodal chord
per vertex pair, growing average degree from four to five for a width-two ring,
then deletes every added chord before repeating. Every admitted change is real;
rejected/dropped offers do not advance the accepted prefix. Original ring partners
stay matched, allowing exact version-referenced query answers without mirroring
the engine. `Pulse.audit` streams the active chord interval rather than allocating
a graph-sized Python edge set. Counted topology streams must be strictly sorted,
canonical non-ring edges; repeated, missing, incorrect and unsized references
must reject rather than certify only a plausible edge count.

Small tests cover every insertion/deletion boundary across multiple cycles at
degrees 4/16/64, independently compare every possible edge and every partner after
each change, checkpoint/reopen, and force stalled persistence/admission rejection
with both IPC batch sizes. These tests are a qualification harness gate, not a
million-vertex growth/drain performance result. Existing frozen-runner soaks are
unchanged by this harness addition.

The schedule's inverse rounding must match its integer-floor arrival timestamps.
At an exact deadline for a non-divisor rate (including 11,000/s), the old inverse
`elapsed * rate // 1e9` can return the preceding index and duplicate an offer.
Use `((elapsed + 1) * rate - 1) // 1e9`, capped at the final slot, to select the
largest index whose rounded deadline has arrived. Deterministic clock cases
cover every deadline at rates 3/7/11,000 over one/two seconds and a skipped-slot
deadline. Total offers plus misses must always reconcile; frozen earlier runners
retain their provenance and must pass their existing count reconciliation.

`--arrival burst` selects a `Burst` schedule for updates while queries retain a
steady rate. Each second's full update quota is offered during its first quarter
at four times the configured average rate, followed by a quiet drain interval.
Planned counts remain `rate * seconds`; timestamp-derived latency includes burst
queueing. Deadline/position mappings are polymorphic; admission, loss accounting,
bounded receipts and exact recovery use the same path as steady arrivals. Late
burst slots are missed, never emitted as an unbounded catch-up batch. Clock tests
cover rounded deadlines, second boundaries, quiet-window waits, skipped slots and
cancellation. Stalled-storage end-to-end tests combine both arrival policies,
all three graph traces and both IPC batch sizes. This is harness coverage, not
evidence that every offered burst can be admitted or a production burst SLA.

## Evidence and limits

### Current installed independent hub stages — 2026-10-03

Steady hub delivery reaches 10,985/s; a fresh combined burst/hub stage on
`3a3c5cf` reaches 10,431/s, with 1.80m queries, 59 checkpoints and exact recovery.
The latter retains 56,554 Busy rejections and twelve accepted scheduled-offer
latencies exceeding one second. These qualify delivered throughput in their
declared envelope, not every offer or a tight tail SLA. Wider repeatability is
still active. [Raw records and provenance](../../benchmarks/results/independent/README.md).

### Harness and earlier measurements

The separate-process runner now supports `--workload hub --degree D` through
the same polymorphic `Traffic` reference as hot, full-ring and growth/drain.
This is the degree-four ring plus D-4 permanent spokes, not an unchanged
average-degree-four graph. Setup runs through bounded durable admission before
the producer clock starts, and is reported separately. Every timed four-edit
cycle deletes `(0,1)`, inserts/deletes `(0,D-1)`, and reinserts `(0,1)`.
All other endpoints remain matched. Queries at the hub check the exact committed
prefix, including all three partial-cycle states and the setup version offset.
Final certificates stream permanent spokes and the optional churn chord.

Admission request IDs include setup, but reported timed changes and offered-count
reconciliation exclude it. Losses never advance the logical trace. Steady and
burst arrivals share bounded IPC, queue/receipt limits, maintenance, exact
query validation and independent restore. Invalid degrees, non-hub degree
arguments and non-degree-four hub rings reject before opening the store.
Tests traverse every graph edge and partner after setup and all repair prefixes,
including degree-128 index promotion, repeated checkpoints, reopen and exact
retry/future mutations. Stalled persistence forces bounded overload for both
arrival policies and IPC batch sizes. At this historical harness-only milestone,
sustained installed-wheel hub measurements were still required; the harness
addition alone did not qualify them. Current scoped stages are recorded above.
All 886 local tests pass; lint, formatting and source types pass. No production
engine, durability or storage code changes are part of this harness extension.

The degree-65536 million-vertex staged hub run falls to 9048 real durable changes/s,
below 10k, while exact audits/recovery pass. Average degree is 4.131064. The trace
includes checkpoint maintenance. This is a demonstrated qualification limitation,
not proof that matching correctness failed. Degree-dependent native free-neighbor
search and maintenance must be measured/optimized before broader support is claimed.
[Raw provenance](../../benchmarks/results/service/README.md).

Paced producers run in the same CPython process as the local service. GIL/native
work, thread scheduling and producer overhead can prevent intended arrivals.
Missed slots are producer losses, not server admission rejections; neither counts
as delivered updates. These runs are not an independent network/process load
generator, a production arrival model, or a power-loss test. Do not claim 10k
delivery from a configured 10k offer rate, or interpret saturation throughput as
successfully handling all offered requests. Hard total RSS/disk limits and an
agreed workload/latency envelope remain separate gates.

Regression coverage checks exact skewed topology/version accounting, bootstrap
failure ownership release, bounded queue/receipt counts, all offered outcomes,
exact recovery, invalid envelopes and deterministic missed-slot behavior.
Uniform closed-loop results and the completed earlier soak remain scoped evidence;
they do not override failing/new workload observations.

Installed-wheel offered-load runs also show a million-vertex 10k/s scheduled
arrival profile delivering only 9561/s: 2745 producer-missed slots and 1573 Busy
responses out of 100000 scheduled arrivals. Ack p99 upper bound is 84.8 ms.
At 100k scheduled/s, gross delivery reaches 32468/s but hundreds of thousands
of updates and 4689 queries reject; this is bounded saturation, not handling the
offered workload. [Raw counts and limitations](../../benchmarks/results/overload/README.md).

### Deterministic power-law Service offered-load profile

`benchmarks/overload.py --workload power-law` adds a paced real-edge workload.
With a fixed seed it constructs a bounded degree-skewed ring-plus-spokes graph,
bootstraps permanent and toggleable edges through `Service`, then chooses timed
edge toggles from a bounded Zipf-weighted selection wheel (exponent 1.2). The
pool size is configurable from 1–8192 per edge set; at most twice that count is
inserted during separately reported setup. Every admitted timed operation flips
one known-present/known-absent chord, so acknowledgments must be real changes.
Busy and producer-missed offers do not advance the edge state, sequence, or update
trace hash.

Run with `--vertices N --rate R --seconds S --query-rate Q --seed K
--skew-edges E`. Output separates bootstrap from timed offers; reconciles admitted,
Busy and producer-missed update and query counts; reports update, offered-to-ack,
queue, execution and query latency histograms; and records the update trace,
topology-plus-partner state digest and maximum degree. Queries select the hot hub
population; their returned versions must be monotone and fall between the durable
bootstrap prefix and the currently admitted prefix. Following shutdown, a fresh
`Durable` reopen checks exact sequence, complete expected topology, proper maximal
matching, and equality with the live full-partner digest.

The new tests validate seeded generator identity, degree skew, rejection-safe
state transitions, CLI options, all offer/loss reconciliations and final recovery.
They establish that the profile is executable and internally auditable, not that
a million-vertex offered-load SLA passes. Query answers are not replay-checked
against every historical version, and this does not complete repeatability,
adversarial, soak, resource-limit, independent-load-generator or power-loss
qualification.

### Short million-vertex power-law samples

Four 10-second source-checkout runs were then executed on macOS 26.7.1 ARM64,
CPython 3.14.8 and SQLite 3.53.4, using seed 599, 1,000 query offers/s, a
degree-four million-vertex ring, 2,048 bootstrap chords and 16 weighted hubs.
All runs passed exact final recovery and proper/maximal matching audits. The
10k-offer repeats delivered 9,538–9,549 real updates/s; the 12k-offer repeats
delivered 11,146–11,151/s. Busy and producer-missed offers were fully reconciled.
Successful query p99 upper bounds were 0.5–0.6 ms. Ack p99 upper bounds were
81.3–84.9 ms at 10k offers and 150.6–152.2 ms at 12k offers. Observed process
peak RSS was 220.5–220.8 MB and measured maximum degree 564–569.

Matching digests agreed across the four runs. Update-trace and graph-state
digests differed because admission losses changed each accepted prefix, rather
than because the seed changed. The 10k offered case misses the real-rate target;
12k offered exceeds 10k in these short local samples but includes Busy and missed
offers and higher ack tails. Treat this only as a repeatability/calibration
probe: it is not an installed-wheel run, sustained SLA, independent producer,
per-version historical-query replay, hard RSS limit or deployment qualification.
See the [recorded results and provenance limits](../../benchmarks/results/overload/power-law-million.json)
and [overload results index](../../benchmarks/results/overload/README.md).
