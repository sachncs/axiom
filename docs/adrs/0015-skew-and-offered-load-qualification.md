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
