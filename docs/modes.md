# Modes

Axiom exposes two operating modes for maintaining a maximal matching
under dynamic edge insertions and deletions.

## `basic`

Single-level algorithm using one *z*-subgraph system.

**Parameters** (derived from `n`):

| Symbol | Value |
|---|---|
| `z` | &lceil;*n*<sup>2/3</sup>&rceil; |
| `r` (phase length) | &lceil;*n*<sup>4/3</sup>&rceil; |
| Subphase length | *r* / *z* &asymp; *n*<sup>2/3</sup> |

**Per-update cost:** &Otilde;(*n*<sup>2/3</sup>) amortised.

**Invariants maintained:** the seven single-level z-system invariants from Section 2 of the paper (degree bounds, P1, P2, &Lambda;, &L;).

**When to use:**

- You want the simplest implementation.
- You don't need the multi-level bound.
- The graph is small enough that the constant-factor matters less than simplicity.

## `tiered`

Multi-level algorithm that stacks `k = &lceil;log<sub>2</sub> &radic;*n*&rceil;`
z-systems at decreasing `z` values.

**Parameters** (derived from `n`):

| Symbol | Value |
|---|---|
| `z_1` | *n* |
| `z_i` | `z_{i-1}` / 2 |
| `z_k` | &asymp; &radic;*n* |
| `k` | &lceil;log<sub>2</sub> &radic;*n*&rceil; &asymp; &half; log *n* |

**Per-update cost:** *n*<sup>1/2+o(1)</sup> amortised (Theorem 1.1).

**Invariants maintained:** all seven from `basic`, plus the multi-level invariant (I3): at most 2&tau; = 64*r*/*z* vertices of *A*<sub>1</sub> are matched by *M*<sup>*</sup> into *R*<sub>1</sub>.

**When to use:**

- You need the best asymptotic bound.
- Your graph is large enough that the lower constant from the multi-level structure pays for the additional bookkeeping.

## Choosing a mode

Use `basic` by default; switch to `tiered` when *n* is large (typically *n* &geq; 1000) and you need the worst-case asymptotic guarantee.

```python
from axiom import Matcher

algo_basic = Matcher(n=100, mode="basic")
algo_tiered = Matcher(n=100, mode="tiered")
```

Or use the strategy classes directly:

```python
from axiom import Matcher
from axiom.rebuild import Basic, Tiered

algo_basic = Matcher(n=100, policy=Basic())
algo_tiered = Matcher(n=100, policy=Tiered())
```

## Limitations

Both modes use the paper's amortised analysis as the theoretical
bound. Empirically, the Python implementation runs slower than the
asymptotic shape would suggest because:

- The adjacency layer uses Python hash sets instead of BSTs (faster
  in practice but worse in the paper's model).
- The colouring uses Vizing's theorem (O(*m* &middot; &Delta;)) rather
  than the paper's cited ABB+26 theorem (O(*m*<sup>1+o(1)</sup>)).
- The multi-level construction rebuilds each level independently from
  the current graph rather than recursively deriving *z*<sub>*i*</sub>-systems
  from *z*<sub>*i*-1</sub>-systems (the latter is described at high level in
  the paper but the pseudocode is not provided).

These are documented as `DEFERRED-OPEN-PROBLEMS` in
`docs/paper_restatement.md`.