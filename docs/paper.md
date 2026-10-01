# Paper coloring

The deterministic colorer is `axiom.Paper`. Its implementation in
`axiom.paper_coloring` uses public, single-word class, method, and state names.
The previous `PaperFanColorer` name and free-function entry points have been
removed; callers must migrate to this API.

```python
from axiom import Paper
from axiom.graph import Adjacency

graph = Adjacency(3)
graph.add_edge(0, 1)
graph.add_edge(1, 2)
colors = Paper().color(graph, 2)
```

| Class | Responsibility |
| --- | --- |
| `Partial` | Proper partial coloring, palette, incidence indexes, alternating paths |
| `Fan`, `Spoke`, `Chain`, `Event`, `Certificate` | Immutable algorithm certificates |
| `Fans` | Separable collection, compatibility, and indexed fan state |
| `Vizing` | Fan construction, chain exploration, activation, and collision resolution |
| `Pruning` | Matching certificates, fan collisions, and surviving-chain reduction |
| `Construction` | Direct fans, witness shifts, matching routing, and small-batch activation |
| `Spectrum` | Color blocks, feasible types, path modification, and sparsification |
| `Extension` | Recursive projection, extension, and merge |
| `Paper` | Complete coloring, recursive seeding, and final certification |

Algorithm implementations reside directly in their methods. Strategies use
class methods with late-bound dispatch, so subclasses can replace an operation
without duplicating orchestration. Composition is explicit: `Paper.construction`,
`Paper.vizing`, `Paper.extension`, `Construction.pruning`, `Construction.vizing`,
`Pruning.vizing`, `Extension.construction`, and `Extension.spectrum` are strategy
classes. A subclass may replace any of these with a compatible subclass.

```python
from axiom.paper_coloring import Construction, Paper

class Recording(Construction):
    selections = 0

    @classmethod
    def collect(cls, coloring, edges):
        cls.selections += 1
        return super().collect(coloring, edges)

class Instrumented(Paper):
    construction = Recording
```

Pruning, chain activation, small-batch activation, type modification, and
sparsification restore their coloring/fan snapshots when their transactional
operation fails. Recursive extension retains its existing partial-progress
failure semantics. The complete ABB+26 near-linear bound remains a separate
release gate.

## Benchmarks

Run from the repository root:

```sh
.venv/bin/python benchmarks/paper.py --sizes 2 8 32 --repeats 7
.venv/bin/python benchmarks/paper.py --scenario complete --family dense --sizes 16 40 64 --repeats 5
```

The benchmark has polymorphic scenarios for pruning collisions, full fan
construction, nontrivial chain flips, and complete coloring. For the first
three, size counts disjoint graph gadgets; for complete coloring, size counts
vertices. Complete coloring supports sparse, dense, star, and bipartite graphs.

JSON output includes Python/platform metadata, graph sizes, minimum/median/maximum
seconds, population standard deviation, a separate peak-memory sample, and a
stable SHA-256 coloring/fan certificate. Each sample uses fresh state and is
verified outside the timed region. Memory tracing runs separately. Complete
coloring includes its own built-in final certificate in the measured operation.
These are engineering timings, not evidence for an asymptotic complexity bound.
