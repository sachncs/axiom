"""Set-semantics, boundaries, and representation invariants for Vertices."""

import pytest

from axiom.vertices import Vertices


def test_vertices_match_reference_set_across_deterministic_edits():
    vertices = Vertices(257)
    reference = set()
    for step in range(1200):
        value = (step * 73) % 257
        if step % 3:
            vertices.add(value)
            reference.add(value)
        else:
            vertices.discard(value)
            reference.discard(value)
        assert vertices == reference
        assert len(vertices) == len(reference)
        assert vertices.check()


def test_vertices_set_algebra_and_reference_equality():
    vertices = Vertices(16, (1, 4, 9, 15))
    reference = {1, 4, 9, 15}
    assert vertices == reference
    assert reference == vertices
    assert {1, 9} <= vertices
    assert vertices >= {4, 15}
    assert vertices | {2} == reference | {2}
    assert vertices & {4, 5} == {4}
    assert vertices - {9} == {1, 4, 15}
    assert {0, 9} - vertices == {0}
    assert vertices.copy() == reference


def test_vertices_boundaries_and_clear_keep_bitmap_consistent():
    vertices = Vertices(10, (0, 7, 9))
    assert len(vertices.positions) == 10
    assert list(vertices) == [0, 7, 9]
    vertices.discard(-1)
    vertices.discard(10)
    with pytest.raises(ValueError, match="integer"):
        vertices.add(True)
    with pytest.raises(ValueError, match=r"\[0, 10\)"):
        vertices.add(10)
    vertices.clear()
    assert not vertices and vertices.check()
    vertices.add(8)
    assert list(vertices) == [8] and vertices.check()


def test_dense_vertices_keep_compact_integer_arrays_for_universe_labels():
    vertices = Vertices(8193, range(8193))
    assert len(vertices.positions) == 8193
    assert len(vertices.members) == 8193
    assert len(vertices) == 8193
    assert vertices.check()
