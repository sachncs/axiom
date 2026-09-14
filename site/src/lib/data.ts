export const SITE = {
  title: "Axiom",
  tagline: "Fully dynamic maximal matching — made deterministic",
  description:
    "Axiom is a pure-Python reproduction of the Chuzhoy–Khanna–Song algorithm (STOC 2026), maintaining a maximal matching under online edge insertions and deletions in O-tilde(n^1/2+o(1)) amortised time.",
  repo: "https://github.com/sachncs/axiom",
  paper: "https://arxiv.org/abs/2605.00797v1",
  readme: "https://github.com/sachncs/axiom/blob/master/README.md",
  docs: "https://github.com/sachncs/axiom/tree/master/docs",
  changelog: "https://github.com/sachncs/axiom/blob/master/CHANGELOG.md",
  license: "https://github.com/sachncs/axiom/blob/master/LICENSE",
  citation: `Chuzhoy, J., Khanna, S., Song, J. (2026).\n  A Faster Deterministic Algorithm for Fully Dynamic Maximal Matching.\n  arXiv:2605.00797v1 (STOC 2026).`,
} as const;

export const NAV = [
  { label: "Product", href: "#product" },
  { label: "Features", href: "#features" },
  { label: "Modes", href: "#modes" },
  { label: "Code", href: "#code" },
  { label: "Install", href: "#install" },
] as const;

export const METRICS = [
  {
    value: "Õ(n^1/2+o(1))",
    label: "amortised update time",
    note: "tiered mode · Theorem 1.1",
  },
  {
    value: "Θ(log n)",
    label: "hierarchy levels",
    note: "k-level recursive partition",
  },
  {
    value: "7",
    label: "invariants verified",
    note: "checked after every update",
  },
  {
    value: "0",
    label: "runtime dependencies",
    note: "pure Python · stdlib only",
  },
] as const;

export const PROBLEM = [
  {
    step: "01",
    title: "The stream",
    body: "Edges arrive and depart one at a time — insertions, deletions, insertions again. The graph never sleeps, and the matching must keep up without ever rebuilding from scratch.",
  },
  {
    step: "02",
    title: "The invariant",
    body: "A maximal matching stays an l̶ocal proof of coverage: every edge touches at least one matched vertex. Recover it instantly, deterministically, after every single update.",
  },
  {
    step: "03",
    title: "The cost",
    body: "The z-subgraph system localises damage so each update costs only Õ(n^1/2+o(1)) amortised work — the fastest known deterministic bound for this problem.",
  },
] as const;

export const FEATURES = [
  {
    icon: "layers",
    title: "Two operating modes",
    body: "basic runs the single-level Õ(n^2/3) algorithm; tiered runs the n^1/2+o(1) k-level recursion with k ≈ ½ log n. Swap policies without touching your code.",
  },
  {
    icon: "graph",
    title: "z-subgraph system",
    body: "The full (A, B, U) partition, S = A ∪ B saturation, Λ(u) and L(a) index lists, and all seven invariants from Section 2 of the paper — implemented, not stubbed.",
  },
  {
    icon: "palette",
    title: "Deterministic colouring",
    body: "Vizing's alternating-path recolouring delivers (Δ+1)-colours, and a degree-ordered greedy fast-path partitions M into colour classes for rematch dispatch.",
  },
  {
    icon: "invariant",
    title: "Invariant checks",
    body: "Independent read-only validators prove maximality, every z-system property, and the multi-level (I3) bound at any moment. Call them from tests or debug scripts.",
  },
  {
    icon: "path",
    title: "Augmenting-path API",
    body: "augment(), try_augment(), and flip() are first-class public methods — no name-mangled privates. Drive the matching machinery directly from your own code.",
  },
  {
    icon: "ledger",
    title: "Empirical ledger",
    body: "Explicit counters track rebuilds, rematch scan sizes, stale cleanups, and greedy fallbacks — a precise account of where every update spends its time.",
  },
] as const;

export const MODES = [
  {
    name: "Basic",
    tag: "single-level · deterministic",
    complexity: "Õ(n^2/3)",
    period: "amortised per update",
    points: [
      "z = ⌈n^2/3⌉ saturation threshold",
      "phase length r = ⌈n^4/3⌉",
      "subphase length r / z",
      "ideal for mid-size graphs & teaching",
    ],
    accent: "cobalt",
    cta: "policy=Basic()",
  },
  {
    name: "Tiered",
    tag: "multi-level · k = Θ(log n)",
    complexity: "n^1/2+o(1)",
    period: "amortised per update",
    points: [
      "z₁ = n, zᵢ = zᵢ₋₁ / 2 recursive levels",
      "k = ⌈log₂ √n⌉ hierarchy depth",
      "level-k threshold z_k ≈ √n",
      "Invariant (I3) enforced after every update",
    ],
    accent: "violet",
    cta: "policy=Tiered()",
  },
] as const;

export const API_SNIPPET = `from axiom import Matcher

algo = Matcher(n=100, mode="tiered")

algo.insert(0, 1)      # edge arrives
algo.insert(2, 3)
algo.delete(1, 0)      # edge leaves

assert algo.maximal()  # still maximal — instantly
print(algo.matching()) # {(2, 3)}
print(algo.size())     # 1
print(algo.stats())    # amortised ledger`;

export const CLI_SNIPPET = `$ axiom --n 20 --mode basic --updates 200 --seed 42

=== Axiom Demo: n=20, mode=basic, updates=200 ===
Completed 200 updates in 0.001s
Final edges: 12
Matching size: 8
Maximal: True`;

export const REBUILD_SNIPPET = `# Strobes of work land on a dark chart —
# matching size stays maximal through every
# update, while the ledger explains the cost.

n=200 · updates=5000 · mode=tiered   ───■── 6.2k upd/s
rebuilds          827
rematch scans     12,913
stale cleanups    —·
greedy fallbacks  31`;

export const INSTALL = {
  pip: "pip install git+https://github.com/sachncs/axiom.git",
  dev: "pip install -e \".[dev]\"",
} as const;

export const FOOTER_LINKS = [
  {
    group: "Project",
    links: [
      { label: "Repository", href: SITE.repo },
      { label: "Documentation", href: SITE.docs },
      { label: "Changelog", href: SITE.changelog },
      { label: "License · MIT", href: SITE.license },
    ],
  },
  {
    group: "Engineering",
    links: [
      { label: "Architecture", href: `${SITE.docs}/architecture.md` },
      { label: "API reference", href: `${SITE.docs}/api.md` },
      { label: "Modes deep-dive", href: `${SITE.docs}/modes.md` },
      { label: "FAQ", href: `${SITE.docs}/faq.md` },
    ],
  },
] as const;