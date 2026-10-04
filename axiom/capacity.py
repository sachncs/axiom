"""Typed resource-admission failures shared by paper transaction journals."""


class JournalCapacityError(MemoryError):
    """Signal that a bounded paper undo journal cannot admit another cell."""
