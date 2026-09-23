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
paper. Parameters decrease geometrically from the largest power of two at
most `n` toward `sqrt(n)`.

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
