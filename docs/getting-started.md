# Getting Started

## Install

```bash
git clone https://github.com/sachncs/fully-dynamic-maximal-matching.git
cd fully-dynamic-maximal-matching
pip install -e .
```

For development, install the optional dependencies too:

```bash
pip install -e ".[dev]"
```

## First Steps

### Basic mode

```python
from axiom import Matcher

algo = Matcher(n=50, mode="basic")

# Create an algorithm instance with 50 vertices
algo.insert(0, 1)
algo.insert(1, 2)
algo.insert(2, 3)

# Delete an edge
algo.delete(1, 2)
```

### Multi-level mode

```python
algo = Matcher(n=50, mode="tiered")
algo.insert(0, 1)
algo.insert(2, 3)
```

### Simulation

```python
import random
from axiom import Matcher
from axiom.simulation import random_updates, replay

algo = Matcher(50, mode="basic")
rng = random.Random(7)
seq = list(random_updates(50, 100, rng))
replay(algo, seq)
assert algo.maximal()
```

### Command-line

```bash
axiom --n 20 --mode basic --updates 200 --seed 42
```

## Next steps

- Read [Architecture](architecture.md) to understand the module layout.
- Read [Modes](modes.md) to choose between `basic` and `tiered`.
- Read [API](api.md) for the full public surface.
- Read [Paper restatement](paper_restatement.md) for the theoretical background.