"""Explicit native maximal-matching core, not yet a durable service."""

class Engine:
    """Own compact graph/partner state and certified local update transactions."""
    def __init__(self, n: int, *, budget: int = 1073741824) -> None:
        """Allocate graph and partner metadata under one native container budget."""
        ...
    @property
    def n(self) -> int:
        """Return the fixed dense vertex universe."""
        ...
    @property
    def version(self) -> int:
        """Read the committed real-mutation sequence; reject unpublished batches."""
        ...
    @property
    def active(self) -> bool:
        """Read allocation-free transaction status, not unpublished topology."""
        ...
    @property
    def poisoned(self) -> bool:
        """Read allocation-free failure status, including after poisoning."""
        ...
    def insert(self, u: int, v: int) -> bool:
        """Insert an edge, repair and certify matching, and report a real change."""
        ...
    def delete(self, u: int, v: int) -> bool:
        """Delete an edge, repair and certify matching, and report a real change."""
        ...
    def partner(self, vertex: int) -> int | None:
        """Read one committed partner without constructing the whole matching."""
        ...
    def size(self) -> int:
        """Read the committed matching edge count in constant time."""
        ...
    def num_edges(self) -> int:
        """Read the committed graph edge count in constant time."""
        ...
    def has_edge(self, u: int, v: int) -> bool:
        """Query committed edge membership."""
        ...
    def degree(self, vertex: int) -> int:
        """Read a committed vertex degree."""
        ...
    def check(self) -> bool:
        """Independently audit all graph/matching invariants; may allocate scratch."""
        ...
    def memory(self) -> dict[str, int]:
        """Report native capacity/budget and diagnostic active/poisoned flags."""
        ...
    def begin(self) -> int:
        """Open an owner-bound private graph/partner transaction."""
        ...
    def commit(self, token: int) -> None:
        """Publish an in-memory transaction, not a durable acknowledgment."""
        ...
    def rollback(self, token: int) -> None:
        """Restore graph, partner/count state and logical version without allocation."""
        ...
    def ring(self, width: int = 2) -> None:
        """Build and audit an isolated regular-ring initialization candidate."""
        ...
    def page(
        self, start: int = 0, limit: int = 1024, version: int | None = None
    ) -> tuple[int, list[tuple[int, int]], int | None]:
        """Return a versioned matching page scanning at most 4096 vertices."""
        ...
