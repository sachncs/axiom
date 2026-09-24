"""axiom: deterministic fully dynamic maximal matching.

This package is a pure-Python implementation based on the deterministic
fully dynamic maximal matching algorithm of Chuzhoy, Khanna, and Song
(arXiv:2605.00797v1, STOC 2026).

Two operating modes are exposed through :class:`Matcher`:

* ``"basic"`` -- a single-level :math:`z`-subgraph system.
* ``"multilevel"`` -- a density-sensitive recursive :math:`k`-level system
  with up to :math:`\\Theta(\\log n)` levels.

The supporting modules provide:

* :class:`Adjacency` -- a thin adjacency-set wrapper that stands in
  for the paper's BST-based adjacency layer.
* :class:`System` and :class:`Hierarchy` -- the
  combinatorial state used by both modes.
* The :math:`z`-system construction primitives
  :func:`build`, :func:`build_hierarchy`,
  :func:`switch`, and :func:`promote`.
* The edge colouring utilities :class:`Greedy`, :class:`Vizing`, and
  :class:`PaperFanColorer`, plus the matching augment/flip helpers.
* :class:`Ledger` and the :mod:`axiom.simulation` /
  :mod:`axiom.parallel` modules -- engineering utilities for empirical
  benchmarking and reproducibility.

Reference:
    Chuzhoy, J., Khanna, S., Song, J. (2026).  *A Faster Deterministic
    Algorithm for Fully Dynamic Maximal Matching*.  arXiv:2605.00797v1.
"""

from axiom.color import (
    Greedy,
    Vizing,
    alternating,
    color_one,
    find,
    flip,
    missing,
    recolor,
)
from axiom.core import Matcher
from axiom.graph import Adjacency
from axiom.hierarchy import Hierarchy, build_hierarchy
from axiom.ledger import Ledger
from axiom.matching import greedy, partner_in, partners
from axiom.paper_coloring import PaperFanColorer
from axiom.parallel import compare, run_parallel
from axiom.simulation import random_updates, replay
from axiom.system import (
    System,
    build,
    promote,
    switch,
)
from axiom.types import Colorer, Edge, Graph, Matching, Vertex, canonical
from axiom.visualize import (
    visualize_adjacency,
    visualize_matching,
    visualize_system,
)

__version__ = "0.6.0.dev0"

__all__ = [
    "Matcher",
    "Adjacency",
    "Greedy",
    "Vizing",
    "PaperFanColorer",
    "System",
    "Hierarchy",
    "Edge",
    "Matching",
    "Vertex",
    "Graph",
    "Colorer",
    "canonical",
    "greedy",
    "partner_in",
    "partners",
    "Ledger",
    "random_updates",
    "replay",
    "visualize_system",
    "visualize_matching",
    "visualize_adjacency",
    "run_parallel",
    "compare",
    "missing",
    "alternating",
    "flip",
    "color_one",
    "recolor",
    "find",
    "build",
    "build_hierarchy",
    "switch",
    "promote",
]
