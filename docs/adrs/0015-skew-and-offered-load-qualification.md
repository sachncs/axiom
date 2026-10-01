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
