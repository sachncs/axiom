# Modes

Axiom exposes two canonical modes for maintaining a maximal matching under
dynamic edge insertions and deletions.

## `basic`

The single-level z-subgraph algorithm. It is the simpler choice for smaller
graphs and uses one z-system with `z = ceil(n^(2/3))`.

```python
from axiom import Matcher

matcher = Matcher(n=100, mode="basic")
```

## `multilevel`

The recursive multi-level algorithm. It derives each finer z-system from the
previous level and uses the level structure `(A_i, N_i, R_i)` defined by the
paper. Type-1 phases use one system with `z = ceil(sqrt(n))` when the
phase-start graph has at most `n^(3/2)` edges. Type-2 phases choose the first
`z` value from the phase-start average degree and halve it geometrically to
the paper's `sqrt(n)/(4 log n)` threshold.

```python
from axiom import Matcher

matcher = Matcher(n=100, mode="multilevel")
```

The hierarchy validator is available for diagnostics:

```python
assert matcher.multi is not None
assert matcher.multi.check()
```

## Guarantees and limits

Both modes maintain a deterministic maximal matching. The multilevel mode
implements recursive construction and multi-level invariants, but the
asymptotic bound should only be interpreted together with the paper's model
assumptions and the implementation's measured performance.

The current adjacency layer uses Python hash sets. Benchmark results should
be reported separately from the theoretical theorem.
