"""Typed interface to native, bounded segmented graph storage."""

from collections.abc import Iterator

def publish(participants: list[tuple[Packed, int]]) -> None:
    """Validate every journal before an allocation-free group commit."""
    ...

class Packed:
    """Own an undirected graph in native arrays and reusable neighbor blocks."""

    def __init__(self, n: int, *, budget: int = 1073741824) -> None:
        """Allocate bounded native vertex metadata without per-vertex Python objects."""
        ...

    @property
    def n(self) -> int:
        """Return the fixed vertex universe size."""
        ...

    @property
    def version(self) -> int:
        """Return the successful real-mutation sequence number."""
        ...

    def add_edge(self, u: int, v: int, *, strict: bool = False) -> None:
        """Insert an edge atomically after reserving both endpoint edits."""
        ...

    def remove_edge(self, u: int, v: int, *, strict: bool = False) -> None:
        """Remove an edge atomically without allocating undo state."""
        ...

    def has_edge(self, u: int, v: int) -> bool:
        """Check edge membership in the native endpoint row."""
        ...

    def degree(self, v: int) -> int:
        """Return a cached endpoint degree."""
        ...

    def neighbors(self, v: int) -> Iterator[int]:
        """Iterate sorted neighbors, rejecting concurrent graph mutation."""
        ...

    def edges(self) -> Iterator[tuple[int, int]]:
        """Stream canonical edges without materializing all edges in Python."""
        ...

    def num_edges(self) -> int:
        """Return the cached number of undirected edges."""
        ...

    def empty(self) -> Packed:
        """Create empty storage with the same vertex universe and native budget."""
        ...

    def copy(self) -> Packed:
        """Clone contents into independent native storage."""
        ...

    def compact(self) -> None:
        """Reclaim unused blocks through a bounded candidate publication."""
        ...

    def memory(self) -> dict[str, int]:
        """Report native allocated capacity, live blocks, and configured budget."""
        ...

    def check(self) -> bool:
        """Independently check symmetry, row degrees, block ownership, and counts."""
        ...

    def ring(self, width: int = 2) -> None:
        """Build an empty graph's regular ring natively with bounded publication."""
        ...

    def begin(self) -> int:
        """Open an owner-bound native mutation journal and return its token."""
        ...

    def commit(self, token: int) -> None:
        """Commit the active journal, rejecting stale tokens or other owners."""
        ...

    def rollback(self, token: int) -> None:
        """Undo journaled edits without allocation and restore the original version."""
        ...
