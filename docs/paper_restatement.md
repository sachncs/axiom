# Paper Restatement and UNKNOWNs

**Title:** A Faster Deterministic Algorithm for Fully Dynamic Maximal Matching  
**Authors:** Julia Chuzhoy (TTIC), Sanjeev Khanna (NYU), Junkai Song (NYU)  
**arXiv:** 2605.00797v1

---

## 1. Problem Definition

Maintain a **maximal matching** in an $n$-vertex simple undirected graph $G$ under a fully dynamic sequence of edge insertions and deletions. The adversary may be adaptive. Amortized update time must be sublinear in $n$.

---

## 2. Key Contributions

1. **Theorem 1.1** — deterministic fully-dynamic maximal matching with amortized update time $n^{1/2+o(1)}$.
2. **Subgraph-system framework** — a new combinatorial object ($z$-subgraph system) tailored for verifying and repairing maximality, distinct from EDCS-based approaches.
3. **Two-level construction** — basic algorithm $\tilde O(n^{2/3})$, then recursive multi-level refinement to $n^{1/2+o(1)}$.
4. **Deterministic edge-colouring** — partition $M$ into $z+1$ matchings via $(\Delta+1)$-edge-colouring (Theorem 2.4, ABB+26).

---

## 3. Notation

| Symbol | Meaning |
|--------|---------|
| $n$ | Number of vertices |
| $m$ | Number of edges (current) |
| $G=(V,E)$ | Current undirected graph |
| $G^{(\tau)}$ | Graph after $\tau$ updates |
| $N_G(v)$ | Neighbors of $v$ in $G$ |
| $\deg_G(v)$ | Degree of $v$ in $G$ |
| $M$ | Edge subset of the $z$-system |
| $M^*$ | Maintained maximal matching |
| $M_1,\dots,M_{z+1}$ | Edge-colour classes of $M$ |
| $(A,B,U)$ | Vertex partition; $S=A\cup B$ |
| $z$ | Degree parameter (basic: $z=\lfloor n^{2/3}\rfloor$) |
| $r$ | Phase length (basic: $r=\lfloor n^{4/3}\rfloor$) |
| $\tau$ | Bound on unmatched $S$-vertices ($\tau=32r/z$) |
| $\hat S$ | Vertices of $S$ currently unmatched by $M^*$ |
| $\Lambda(u)$ | $N_G(u)\cap(B\cup U)$ for $u\in U$ |
| $L(a)$ | $N_G(a)\cap U$ for $a\in A$ |
| $H$ | Directed auxiliary graph on $B\cup U$ |
| $A_1,A_2$ | Split of level-1 $A$ in multi-level system |
| $N_1,R_1$ | Subsets for level-1 restriction |
| $z_i$ | Level-$i$ degree parameter ($z_1=n$, $z_i=z_{i-1}/2$, $z_k\approx\sqrt n$) |
| $k$ | Number of levels, $\Theta(\log n)$ |

---

## 4. Graph and Matching Invariants

### 4.1 Settled Vertices (Definition 2.1)

A vertex $v$ is **settled** w.r.t. matching $M$ iff either:
- (i) $v$ is incident to an edge of $M$, or
- (ii) every $y\in N_G(v)$ is incident to an edge of $M$.

$M$ is maximal $\iff$ every vertex is settled.

### 4.2 Observation 2.2
If every neighbor of $v$ is settled under $M$, then $v$ is settled under $M$.

### 4.3 Observation 2.3
Let $M$ be maximal. Obtain $M'$ from $M$ by deleting/inserting edges. Let $E_D=M\setminus M'$ and $V_D$ the endpoints of $E_D$. If every vertex of $V_D$ is settled w.r.t. $M'$, then $M'$ is maximal.

---

## 5. The $z$-Subgraph System

### 5.1 Definition

For integer $1\le z\le n$, a **$z$-subgraph system** consists of:
- an edge subset $M\subseteq E(G)$,
- a vertex partition $(A,B,U)$ with $S=A\cup B$.

Requirements:
1. **Degree bounds in $M$:** Every $v\in S$ is incident to exactly $z$ edges of $M$; every $u\in U$ is incident to at most $z$ edges of $M$.
2. **$U$-$U$ degree bound:** Every $u\in U$ satisfies $|N_G(u)\cap U|\le z$.
3. **Property P1:** Every $u\in U$ satisfies $|N_G(u)\cap B|\le 2z$.
4. **Property P2:** For every $a\in A$, every edge $(a,v)\in M$ incident to $a$ has $v\in S$.
5. **Auxiliary lists:**
   - For each $u\in U$, $\Lambda(u)=N_G(u)\cap(B\cup U)$. Size $|\Lambda(u)|=O(z)$.
   - For each $a\in A$, $L(a)=N_G(a)\cap U$.

### 5.2 Construction (Two-step deterministic algorithm, $\tilde O(n+m)$)

**Step 1:** Greedily select a maximal edge set $M$ such that no vertex participates in more than $z$ edges of $M$. Place into $S$ all vertices with exactly $z$ incident $M$-edges; remaining vertices form $U$. Partition $S$ into $A$ (all $M$-neighbors lie in $S$) and $B$ (at least one $M$-neighbor in $U$). Initialize $\Lambda(\cdot)$ and $L(\cdot)$.

**Step 2:** Process each $u\in U$:
- If $u$ has at least $z$ neighbors in $B$, insert edges from $u$ to $B$ into $M$ until $u$ is incident to exactly $z$ such edges, then move $u$ into $S$ (specifically into $B$).
- If a vertex in $B$ loses all its $M$-edges to $U$, promote it to $A$.
- Edge-switching inside $B$ preserves degree bounds.
- Update lists accordingly.

Result is a valid $z$-subgraph system.

---

## 6. Level Structure and Recursive Refinement

### 6.1 Basic (single-level) algorithm

Parameters: $z=\lfloor n^{2/3}\rfloor$, phase length $r=\lfloor n^{4/3}\rfloor$.

At phase start: rebuild $z$-system from scratch ($\tilde O(n^2)$, amortized $\tilde O(n^{2/3})$ over phase).

Inside a phase:
1. Compute $(z+1)$-edge-colouring of $M$ (Theorem 2.4), yielding matchings $M_1,\dots,M_{z+1}$.
2. In a typical colour class, all but at most $2|S|/z$ vertices of $S$ are matched.
3. Assume $M_1$ is such a class. Over $r$ deletions, most $M_i$ lose at most $2r/z$ edges. Some class leaves at most $32r/z$ vertices of $S$ unmatched; denote $\tau=32r/z$.
4. Divide each phase into subphases of $\lfloor r/z\rfloor\approx n^{2/3}$ updates ($\le 2z$ subphases).

Invariants enforced throughout a subphase:
- **I1:** $M_1$ matches all but at most $2\tau=64r/z$ vertices of $S$.
- **I2:** At most $2\tau$ vertices of $A$ are matched by $M^*$ into $U$.

### 6.2 Multi-level algorithm

Choose decreasing sequence $z_1>z_2>\dots>z_k$ with $z_1=n$, $z_i=z_{i-1}/2$, $z_k\approx\sqrt n$. Then $k=\Theta(\log n)$.

Level-1 phases of length $r_1$ begin with full $z_1$-system built in $\tilde O(m+n)$ time.
Rather than using it directly, construct a $z_2$-system from it in $O(n^{1+o(1)}z_1)$ time, faster than rebuilding when graph is dense.

Given $z_1$-system $\mathcal S$ and deleted-edge set $E_D$ not yet applied to $\mathcal S$, select small subset $E'_D\subseteq E_D$ with $|E'_D|\le (z_2/z_1)|E_D|$ and build $z_2$-system $\mathcal S'$ for graph $G'=G^{(\tau)}\setminus(E_D\setminus E'_D)$. Edges $E'_D$ processed as adversarial deletions before new deletions of shorter level-2 phase.

**2-level $z$-subgraph system** (generalizable to $k$ levels):
- Split $A$ into $A_1\cup A_2$.
- Maintain $N_1\subseteq A_2\cup B$ so every $M$-edge incident to $A_1$ stays inside $A_1\cup N_1$.
- Define $R_1=V\setminus(A_1\cup N_1)$.
- For $a\in A_1$, $L(a)$ records neighbors in $R_1$ only. Lists inherited from previous level; need not change when new vertices enter $A$.
- For $a\in A_2$, standard requirement $L(a)=N_G(a)\cap U$ holds.
- **Invariant I3:** At most $2\tau$ vertices of $A_1$ are matched by $M^*$ into $R_1$.

Extending to $k=O(\log n)$ levels with $z_k\approx\sqrt n$ and level-$k$ phases of roughly $n$ updates achieves $n^{1/2+o(1)}$ amortized bound.

---

## 7. Update Procedures

### 7.1 Insertions

The paper focuses on deletions for the basic algorithm; insertions are handled by rebuilding or by treating them as part of the phase-update counter. In the decremental outline, insertions can be handled by the same verification-and-repair framework (Observation 2.3). The exact insertion-specific local-search pseudocode is **not provided** in the excerpt.

### 7.2 Deletions

When an edge $e\in M^*$ is deleted, its endpoints become free. Repair by rematching each endpoint according to its partition:

- **Rematching $U$:** Each $u\in U$ has $O(z)$ neighbors in $U\cup B$ via $\Lambda(u)$. Scan $\hat S$ (size $O(r/z)$). Time $\tilde O(z+r/z)$.
- **Rematching $B$:** Use directed auxiliary graph $H$ on $B\cup U$. For unmatched $u\in U$, outgoing edges to $\Lambda(u)$. If $b\in B$ becomes unmatched, check incoming edge in $H$ for unmatched $u\in U$; otherwise scan $\hat S$. Updates to $H$ cost $\tilde O(z)$ per status change.
- **Rematching $A$:** Difficult because $L(a)$ can be long. Give $A$ priority: scan first $2\tau+1$ entries of $L(a)$. By I2, some encountered $u$ is not matched to $A$ in $M^*$. Insert $(a,u)$ into $M^*$. If $u$ was matched to $u'\in B\cup U$, delete that edge (from $M^*$ and from $M_1$ if present) and rematch $u'$ efficiently. Scan cost $O(r/z)$.

At subphase boundaries, augment $M_1$ using augmenting paths in $M_i\cup M_1$ (for an appropriate $M_i$ that still leaves few $S$-vertices unmatched), restoring invariants with only $O(r/z)$ vertices changing status.

### 7.3 Total Phase Cost

$\tilde O\bigl(n^2 + n^{1+o(1)}z + r(z + r/z)\bigr)$. Dividing by $r$ and substituting $z=n^{2/3}$, $r=n^{4/3}$ gives $\tilde O(n^{2/3})$ amortized time.

---

## 8. Initialization Logic

- Basic mode: set $z$, $r$, build $z$-system from scratch, partition $M$ into matchings via edge-colouring, initialize $M^*$ extending $M_1$ to maximal matching.
- Multi-level mode: set $z_1,\dots,z_k$, build level-1 system, derive finer levels recursively, initialize $M^*$.

---

## 9. Edge-Colouring / Auxiliary Mechanisms

Theorem 2.4 (ABB+26): deterministic $(\Delta+1)$-edge-colouring in $O(m^{1+o(1)})$ time. The paper uses this to split $M$ (max degree $\le z$) into $z+1$ matchings. Full pseudocode of ABB+26 is **not provided**.

---

## 10. Amortized-Time Analysis Dependencies

- Phase length $r$ vs. rebuild cost $\tilde O(n^2)$.
- Edge-colouring cost $O(n^{1+o(1)}z)$.
- Rematching costs: $\tilde O(z)$ for $U$, $\tilde O(z)$ for $B$ via $H$, $O(r/z)$ for $A$.
- Subphase boundary augmentation cost.
- Recursive construction cost for multi-level: deriving $z_i$-system from $z_{i-1}$-system.

---

## 11. Theorem Statements and Parameter Tradeoffs

| Theorem | Statement |
|---------|-----------|
| Theorem 1.1 | Deterministic fully-dynamic maximal matching, amortized update time $n^{1/2+o(1)}$. |
| Theorem 2.4 | Deterministic $(\Delta+1)$-edge-colouring in $O(m^{1+o(1)})$ time (ABB+26). |

Parameters:
- Basic: $z=n^{2/3}$, $r=n^{4/3}$, subphase length $r/z=n^{2/3}$.
- Multi-level: $z_1=n$, $z_i=z_{i-1}/2$, $z_k\approx\sqrt n$, $k=\Theta(\log n)$.

---

## 12. Experimental Setup

**Not present** in the provided excerpt.

---

## 13. Open Problems / Deferred Ideas

**Not present** in the provided excerpt.

---

## 14. UNKNOWNs / Ambiguities — Status (v0.5.0)

Each item below is tagged with one of:

- **RESOLVED** &mdash; the implementation addresses this with the cited paper constant or a clearly documented heuristic.
- **DEFERRED-OPEN-PROBLEM** &mdash; the paper excerpt does not provide enough detail to implement faithfully. Documented here so the gap is visible.
- **ACCEPTED-HEURISTIC** &mdash; the implementation substitutes a documented alternative algorithm with the same correctness contract.

1. **Theorem 2.4 full statement and algorithm** &mdash; DEFERRED-OPEN-PROBLEM. Text truncated mid-theorem; the cited *O*(*m*<sup>1+o(1)</sup>) bound is not implemented.
2. **Sections 3-6 (truncated)** &mdash; DEFERRED-OPEN-PROBLEM. Full construction pseudocode, update procedures, multi-level derivation, and analysis not provided in the excerpt.
3. **Exact phase constants** &mdash; RESOLVED. Paper states $\tau=32r/z$ and $2\tau$ bounds. Implemented in `axiom.core.Matcher` and `axiom.rebuild.Tiered`.
4. **Insertion handling pseudocode** &mdash; ACCEPTED-HEURISTIC. Paper outlines the decremental algorithm; insertions are handled by the same verification-and-repair framework (Observation 2.3) with a fast-path swap for (A, U) edges.
5. **Subphase boundary augmentation** &mdash; RESOLVED. Exact augmenting-path procedure implemented in `axiom.augment.augment` (BFS over alternating paths) and exposed publicly as `Matcher.augment()`.
6. **Multi-level recursive derivation** &mdash; DEFERRED-OPEN-PROBLEM. Deriving $z_i$-system from $z_{i-1}$-system described at high level. Exact edge-set selection $E'_D$ and list-inheritance mechanics unspecified. Each level is rebuilt independently.
7. **Exact partition rule for $A_1/A_2$ and $N_1$** &mdash; ACCEPTED-HEURISTIC. Paper says "maintain $N_1\subseteq A_2\cup B$ so that every $M$-edge incident to $A_1$ stays inside $A_1\cup N_1$." Construction rule not provided. Implemented as a sorted split of $A$ into $A_1$ and $A_2$.
8. **ABB+26 edge-colouring** &mdash; ACCEPTED-HEURISTIC. No pseudocode provided. Substituted with `Vizing` (Vizing's theorem with backtracking fallback) and `Greedy` (degree-ordered greedy).
9. **Auxiliary graph $H$ update rules** &mdash; RESOLVED. The auxiliary graph $H$ was removed entirely (see commit 17, `refactor!: remove dead aux_graph`). The rematch dispatch over $\Lambda(u)$ and /L(a) achieves the same routing without an explicit graph structure.
10. **Exact constant in I3** &mdash; RESOLVED. Paper says "at most $O(r/z)$" and in the multi-level summary says "$2\tau$" ($\tau=32r/z$), so $64r/z$ is the constant. Implemented in `axiom.hierarchy.Hierarchy.check_i3` and `axiom.invariant.check_i3`; maintained after every update in tiered mode via `Hierarchy.maintain_i3`.
11. **Rebuild of $M^*$ from $M_1$** &mdash; RESOLVED. Paper says "inspect all $u\in U$ and all pairs inside $\hat S$, costing $\tilde O(nz+nr/z)$." Implemented in `Matcher.refresh()` as a deterministic greedy scan over vertices in increasing order.
12. **Deterministic seeding / tie-breaking** &mdash; RESOLVED. Greedy steps use sorted vertex order for determinism; reproducible from the seed.
