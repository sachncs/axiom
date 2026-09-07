"""Explicit counters for update work and phase-level accounting.

The paper's amortised-time analysis is not directly executable in Python:
the constants in the analysis depend on the hidden costs of the BST
adjacency lists, the ABB+26 colouring routine, and the Vizing flip.
This module implements **explicit counters** that record the work
actually performed by the Python reproduction -- number of updates,
rebuilds, and the size of every per-vertex scan.  Experiments can use
these counters to diagnose where time is spent without claiming any
asymptotic bound.

Empirical interpretation:
    * ``total_updates`` ≈ total number of insert + delete calls
      accepted by the algorithm (the paper calls this the "update
      count").
    * ``phase_rebuilds`` should grow roughly linearly with
      ``total_updates / phase_length``; a deviation indicates a bug.
    * The three ``rematch_*_scans`` fields are the empirical analogues
      of the amortised scan costs in the paper's analysis.  They sum
      to ``phase_update_work`` so the average scan length can be
      compared against the theoretical bounds.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Ledger:
    """Counters for auditing the cost of dynamic updates.

    Every counter starts at zero and increments monotonically.  The
    counters are intentionally simple int fields so they can be exposed
    cheaply through :meth:`snapshot`.

    Attributes:
        total_updates: Total accepted insert + delete operations.
        total_insertions: Insertions only.
        total_deletions: Deletions only (including no-op deletes of
            non-existent edges, which are still recorded as a deletion).
        phase_rebuilds: Number of full :math:`z`-system rebuilds.
        subphase_rebuilds: Number of :math:`M_1` augmentations at
            subphase boundaries.
        rematch_u_scans: Cumulative vertex count scanned during
            :func:`axiom.core.Matcher.__rematch_u`.
        rematch_b_scans: Same, for :func:`axiom.core.Matcher.__rematch_b`.
        rematch_a_scans: Same, for :func:`axiom.core.Matcher.__rematch_a`.
        greedy_rebuilds: Times the full greedy reconstruction of
            :math:`M^*` was used as a fallback.
        stale_cleanups: Total edges removed from :math:`M^*` because
            they had been deleted from the graph.
        phase_update_work: A running tally of per-phase work units,
            reset by :meth:`record_phase_rebuild`.  Excluded from the
            default ``repr`` because it is mostly internal state.
    """

    total_updates: int = 0
    total_insertions: int = 0
    total_deletions: int = 0
    phase_rebuilds: int = 0
    subphase_rebuilds: int = 0
    rematch_u_scans: int = 0
    rematch_b_scans: int = 0
    rematch_a_scans: int = 0
    greedy_rebuilds: int = 0
    stale_cleanups: int = 0
    phase_update_work: int = field(default=0, repr=False)

    def record_insertion(self) -> None:
        """Record a successful (or attempted) insertion."""
        self.total_updates += 1
        self.total_insertions += 1
        self.phase_update_work += 1

    def record_deletion(self) -> None:
        """Record a successful deletion or a no-op delete of an absent edge."""
        self.total_updates += 1
        self.total_deletions += 1
        self.phase_update_work += 1

    def record_phase_rebuild(self, work_estimate: int = 0) -> None:
        """Record a full phase rebuild and reset the per-phase work tally.

        ``work_estimate`` is the constant to which the rebuild's cost
        should be charged against the phase budget.  The reproduction
        does not have a precise measurement and uses zero.
        """
        self.phase_rebuilds += 1
        self.phase_update_work = work_estimate

    def record_subphase_rebuild(self, work_estimate: int = 0) -> None:
        """Record a subphase :math:`M_1`-augmentation step."""
        self.subphase_rebuilds += 1
        self.phase_update_work += work_estimate

    def record_rematch_u_scan(self, scanned: int = 1) -> None:
        """Record a :func:`rematch_u` call and the number of vertices it scanned."""
        self.rematch_u_scans += scanned
        self.phase_update_work += scanned

    def record_rematch_b_scan(self, scanned: int = 1) -> None:
        """Record a :func:`rematch_b` call and the number of vertices it scanned."""
        self.rematch_b_scans += scanned
        self.phase_update_work += scanned

    def record_rematch_a_scan(self, scanned: int = 1) -> None:
        """Record a :func:`rematch_a` call and the number of vertices it scanned."""
        self.rematch_a_scans += scanned
        self.phase_update_work += scanned

    def record_greedy_rebuild(self, work: int = 0) -> None:
        """Record a fallback greedy rebuild of :math:`M^*`."""
        self.greedy_rebuilds += 1
        self.phase_update_work += work

    def record_stale_cleanup(self, count: int = 1) -> None:
        """Record the removal of ``count`` stale edges from :math:`M^*`."""
        self.stale_cleanups += count
        self.phase_update_work += count

    def snapshot(self) -> dict[str, int]:
        """Return a read-only snapshot of every counter.

        The returned mapping is independent of this instance, so the
        caller may mutate it freely.  The internal
        ``phase_update_work`` field is omitted because it is a running
        tally reset on phase rebuilds rather than a cumulative total.
        """
        return {
            "total_updates": self.total_updates,
            "total_insertions": self.total_insertions,
            "total_deletions": self.total_deletions,
            "phase_rebuilds": self.phase_rebuilds,
            "subphase_rebuilds": self.subphase_rebuilds,
            "rematch_u_scans": self.rematch_u_scans,
            "rematch_b_scans": self.rematch_b_scans,
            "rematch_a_scans": self.rematch_a_scans,
            "greedy_rebuilds": self.greedy_rebuilds,
            "stale_cleanups": self.stale_cleanups,
        }
