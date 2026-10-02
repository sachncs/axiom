"""Bounded comparison of paper state for replay and rollback qualification.

This diagnostic format has no decoder and is NOT a durable checkpoint. Capture
only on the owning thread, between operations. It deliberately includes cached
and redundant fields: rebuilding a valid but different matching is not recovery.
Mutable objects receive traversal references, not process addresses, so aliases
are compared across independent executions. Native allocation capacity and undo
token history are excluded; logical graph versions and topology are included.
"""

from __future__ import annotations

import json
import math
from dataclasses import fields
from typing import Any

from axiom.color import Greedy, Vizing
from axiom.core import Matcher
from axiom.graph import Adjacency
from axiom.hierarchy import Hierarchy
from axiom.ledger import Ledger
from axiom.paper_coloring import Fan, Fans, Paper, Partial
from axiom.rebuild import Basic, Multilevel
from axiom.storage import Packed
from axiom.system import System


class Witness:
    """Capture exact supported logical state without mutating its source.

    Unknown record types/fields fail closed instead of silently omitting state.
    Limits bound traversal nodes, depth, and encoded bytes, not process RSS.
    This is an O(state-size) diagnostic, never an update-path replacement for
    a mutation journal. Use a fresh instance or ``capture`` for each comparison.
    """

    schema = {
        Matcher: frozenset(
            [
                "H",
                "H_reverse",
                "H_tilde",
                "H_tilde_reverse",
                "S_hat",
                "accountant",
                "bad_vertices",
                "colorer",
                "deleted_edges",
                "eta",
                "failed",
                "graph",
                "inserted_edges",
                "inserted_incident_counts",
                "inserted_incident_edges",
                "k",
                "level_phase_indices",
                "level_phase_lengths",
                "level_phase_updates",
                "level_zs",
                "matched_edges",
                "matched_vertices",
                "matchings",
                "mode",
                "multi",
                "n",
                "partner_map",
                "phase_base_graph",
                "phase_base_system",
                "phase_graph",
                "phase_length",
                "policy",
                "seed_matching",
                "subphase_count",
                "subphase_length",
                "system",
                "update_count",
                "z",
            ]
        ),
        Adjacency: frozenset({"n", "adj", "edge_count"}),
        System: frozenset(field.name for field in fields(System)),
        Hierarchy: frozenset(field.name for field in fields(Hierarchy)),
        Ledger: frozenset(field.name for field in fields(Ledger)),
        Partial: frozenset({"graph", "palette", "assignments", "incident", "index"}),
        Fans: frozenset(
            {"members", "spokes", "assignments", "assigned", "vertices", "types"}
        ),
        Greedy: frozenset(),
        Vizing: frozenset(),
        Paper: frozenset(),
        Basic: frozenset(),
        Multilevel: frozenset(),
    }

    def __init__(
        self, *, nodes: int = 1_000_000, depth: int = 64, capacity: int = 16 << 20
    ) -> None:
        """Set positive integer diagnostic limits, rejecting booleans."""
        for limit in (nodes, depth, capacity):
            if type(limit) is not int or limit <= 0:
                raise ValueError("witness limits must be positive integers")
        self.nodes = nodes
        self.depth = depth
        self.capacity = capacity
        self.remaining = nodes
        self.references: dict[int, int] = {}
        self.objects: list[Any] = []

    def charge(self, depth: int) -> None:
        """Account for one visited value, including ordering keys."""
        if depth > self.depth or self.remaining <= 0:
            raise ValueError("witness traversal limit exceeded")
        self.remaining -= 1

    def atom(self, value: Any, depth: int) -> Any:
        """Encode immutable values with distinct, deterministic type tags."""
        self.charge(depth)
        kind = type(value)
        if value is None:
            return ["none"]
        if kind in (bool, int, str):
            return [kind.__name__, value]
        if kind is float and math.isfinite(value):
            return ["float", value.hex()]
        if kind is tuple:
            return ["tuple", [self.atom(item, depth + 1) for item in value]]
        if kind is frozenset:
            return ["frozenset", self.order(value, depth + 1)]
        if kind is Fan:
            return [
                "fan",
                [
                    self.atom(getattr(value, field.name), depth + 1)
                    for field in fields(Fan)
                ],
            ]
        raise TypeError(f"unsupported witness atom: {kind.__module__}.{kind.__name__}")

    def order(self, values: Any, depth: int) -> list[Any]:
        """Order immutable keys/members without repr, hashes, or object addresses."""
        encoded = [self.atom(value, depth) for value in values]
        return sorted(encoded, key=lambda value: json.dumps(value, ensure_ascii=True))

    def encode(self, value: Any, depth: int = 0) -> Any:
        """Traverse supported records and preserve mutable reference structure."""
        self.charge(depth)
        kind = type(value)
        if kind is tuple:
            return ["tuple", [self.encode(item, depth + 1) for item in value]]
        if kind not in (dict, list, set, Packed) and kind not in self.schema:
            return self.atom(value, depth)
        address = id(value)
        if address in self.references:
            return ["ref", self.references[address]]
        reference = len(self.references)
        self.references[address] = reference
        # Retain temporary native topology records too: otherwise their freed
        # addresses could be reused and mistaken for aliases later in traversal.
        self.objects.append(value)
        if kind is list:
            content = [self.encode(item, depth + 1) for item in value]
        elif kind is set:
            content = self.order(value, depth + 1)
        elif kind is dict:
            # Sort encoded keys, then visit values in that order: insertion
            # order must not influence reference numbering.
            entries = [(self.atom(key, depth + 1), item) for key, item in value.items()]
            entries.sort(key=lambda entry: json.dumps(entry[0], ensure_ascii=True))
            content = [[key, self.encode(item, depth + 1)] for key, item in entries]
        elif kind is Packed:
            if value.num_edges() > self.remaining:
                raise ValueError("witness traversal limit exceeded")
            content = self.encode(
                {
                    "n": value.n,
                    "version": value.version,
                    "budget": value.memory()["budget"],
                    "edges": list(value.edges()),
                },
                depth + 1,
            )
        else:
            attributes = vars(value)
            if attributes.keys() != self.schema[kind]:
                raise TypeError(f"unsupported witness fields: {kind.__name__}")
            content = [
                [name, self.encode(attributes[name], depth + 1)]
                for name in sorted(attributes)
            ]
        return [kind.__module__ + "." + kind.__name__, reference, content]

    def capture(self, value: Any) -> bytes:
        """Return canonical bytes; failed capture is reusable and leaves no state."""
        self.remaining = self.nodes
        self.references = {}
        self.objects = []
        try:
            encoded = self.encode(value)
            result = bytearray()
            serializer = json.JSONEncoder(ensure_ascii=True, separators=(",", ":"))
            for fragment in serializer.iterencode(["axiom-witness-v1", encoded]):
                data = fragment.encode("ascii")
                if len(data) > self.capacity - len(result):
                    raise ValueError("witness byte limit exceeded")
                result.extend(data)
            return bytes(result)
        finally:
            self.references.clear()
            self.objects.clear()
