# FAQ

## What is Axiom?

Axiom is a pure-Python reproduction of *A Faster Deterministic Algorithm for Fully Dynamic Maximal Matching* by Chuzhoy, Khanna, and Song (STOC 2026, arXiv:2605.00797v1). It maintains a maximal matching in an undirected graph under online edge insertions and deletions in &Otilde;(*n*<sup>1/2+o(1)</sup>) update time.

## How do I install it?

```bash
git clone https://github.com/sachncs/fully-dynamic-maximal-matching.git
cd fully-dynamic-maximal-matching
pip install -e ".[dev]"
```

## How do I use it?

```python
from axiom import Matcher

algo = Matcher(n=100, mode="basic")
algo.insert(0, 1)
algo.delete(0, 1)
assert algo.maximal()
```

## What's the difference between `basic` and `tiered`?

- `basic` uses one *z*-subgraph system with *z* = *n*<sup>2/3</sup>; per-update cost is &Otilde;(*n*<sup>2/3</sup>).
- `tiered` stacks *k* = log *n* systems at decreasing *z* values; per-update cost is *n*<sup>1/2+o(1)</sup>.

Read [Modes](modes.md) for the full parameter table.

## How do I run the benchmark?

```bash
python benchmarks/bench_axiom.py --n 200 --updates 5000 --mode basic
```

## How do I run the tests?

```bash
pytest tests/
```

## How do I contribute?

Read [CONTRIBUTING.md](../CONTRIBUTING.md) for the workflow.

## What are the limitations?

1. **Empirical counters vs asymptotic guarantees.** The `Ledger` reports what actually happened in Python. The paper's amortised bounds assume a BST-based adjacency layer; the Python reproduction uses hash sets.
2. **ABB+26 colouring.** The paper cites a deterministic (&Delta;+1)-colouring in *O*(*m*<sup>1+o(1)</sup>) time. The implementation substitutes Vizing's theorem plus a degree-ordered greedy colourer, both of which run in *O*(*m* &middot; &Delta;) worst case.
3. **Multi-level derivation.** The paper derives a *z*<sub>*i*</sub>-system from a *z*<sub>*i*-1</sub>-system in *O*(*n*<sup>1+o(1)</sup>*z*<sub>1</sub>) time. The implementation rebuilds each level independently from the current graph.
4. **Deferred open problems.** Documented in `docs/paper_restatement.md` (sections 14.3, 14.6, 14.7, 14.10, 14.11).

## How do I cite Axiom?

```
Chuzhoy, J., Khanna, S., Song, J. (2026).
A Faster Deterministic Algorithm for Fully Dynamic Maximal Matching.
arXiv:2605.00797v1.
```

## Who maintains Axiom?

Sachin ([sachncs@gmail.com](mailto:sachncs@gmail.com)). Open an issue on GitHub for bugs or feature requests.

## What's the licence?

MIT. See [LICENSE](../LICENSE).