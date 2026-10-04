# Durable paper-engine diagnostics

These JSON files are raw one-run diagnostics, not qualification passes. They
record one million vertices, a degree-four ring, 65,536 preloaded spokes at a
single hub, and 256 measured churn updates at that hub. Each run independently
certified topology/maximality and exact recovery. The Basic and Multilevel runs
used the same seed and produced matching trace/state digests, but there is only
one repeat per mode; variance and run-to-run stability are unknown.

The run crossed a real capacity boundary in the previous implementation:
`Systems` attempted to snapshot a hub-sized cache row into its fixed journal and
raised `system journal capacity exceeded`. [ADR 0119](../../../docs/adrs/0119-delta-journal-system-rows.md)
replaces that row snapshot with inverse edit deltas. The retained run results
after the fix show that the capacity error is gone, while performance and
recovery remain poor under extreme skew: Basic delivered about 1.47k measured
updates/s with 280 s replay; Multilevel delivered about 215/s with 951 s replay
and about 1.96 GB peak RSS. Neither result approaches the 10k/s target.

The benchmark excludes the 65,536 preload operations from measured churn
throughput and reports preload time separately. The benchmark process peak RSS
includes setup, churn, audits and recovery; it is not steady-state graph-only
memory. WAL/SHM size is sampled during churn. Both results are macOS ARM64
source-checkout runs using CPython 3.11.16 and SQLite 3.53.1, with working-tree
changes committed unchanged as `bd71bac`.

Reproduce either profile with a fresh database path:

```sh
uv run python benchmarks/durable.py \
  --database /private/tmp/axiom-basic-hub.db \
  --vertices 1000000 --pairs 128 --batch 256 --seed 599 \
  --mode basic --workload hub-churn --hub-degree 65536
```

Repeat across seeds and fresh processes before drawing repeatability conclusions.
This result does not qualify overload, bursts, sustained Service traffic, hard
resource limits, or deployment readiness. The very long Multilevel replay also
shows that passing exact recovery is not equivalent to an acceptable recovery
time. Qualification remains open in both modes.
