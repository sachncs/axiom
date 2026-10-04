from __future__ import annotations

from typing import Any

import pytest

from axiom.partners import Partners


def test_mapping_basics_views_and_dict_conversion() -> None:
    partners = Partners(6, {1: 4, 4: 1})
    assert len(partners) == 2
    assert partners[1] == 4
    assert 1 in partners and 0 not in partners
    assert list(partners) == [1, 4]
    assert list(partners.values()) == [4, 1]
    assert list(partners.items()) == [(1, 4), (4, 1)]
    assert dict(partners) == {1: 4, 4: 1}
    assert partners == {1: 4, 4: 1}
    partners[1] = 3
    assert partners[1] == 3
    partners[2] = 2  # Self-pairs are a cell-level concern, not a map rule.
    assert partners[2] == 2


def test_pop_delete_clear_and_live_views() -> None:
    partners = Partners(5, {0: 1, 1: 0})
    values = partners.values()
    assert partners.pop(0) == 1
    assert partners.pop(3, None) is None
    with pytest.raises(KeyError):
        partners.pop(3)
    with pytest.raises(KeyError):
        del partners[0]
    partners[3] = 2
    assert list(values) == [0, 2]
    partners.clear()
    assert len(partners) == 0
    assert dict(partners) == {}
    assert partners.n == 5


@pytest.mark.parametrize("bad", [True, False, 1.0, "1", None])
def test_rejects_non_integer_keys_and_partners(bad: Any) -> None:
    partners = Partners(3)
    with pytest.raises(TypeError, match="key"):
        partners[bad] = 1
    with pytest.raises(TypeError, match="partner"):
        partners[1] = bad
    with pytest.raises(TypeError, match="key"):
        partners[bad]


@pytest.mark.parametrize("vertex", [-1, 3])
def test_rejects_out_of_universe_key_and_partner(vertex: int) -> None:
    partners = Partners(3)
    with pytest.raises(ValueError, match="key"):
        partners[vertex] = 1
    with pytest.raises(ValueError, match="partner"):
        partners[1] = vertex
    with pytest.raises(ValueError, match="key"):
        _ = partners[vertex]


@pytest.mark.parametrize(
    "size, error", [(True, TypeError), (1.5, TypeError), (-1, ValueError)]
)
def test_rejects_invalid_universe(size: Any, error: type[Exception]) -> None:
    with pytest.raises(error):
        Partners(size)


def test_rejects_universe_that_cannot_be_addressed_by_signed_32_bit_values() -> None:
    with pytest.raises(ValueError, match="32-bit"):
        Partners(2**31 + 1)


def test_constructor_rejects_malformed_mapping_entries() -> None:
    with pytest.raises(ValueError, match="partner"):
        Partners(4, [(0, 4)])
    with pytest.raises(ValueError, match="key"):
        Partners(4, [(-1, 0)])


def test_empty_and_zero_size_boundaries() -> None:
    partners = Partners(0)
    assert len(partners) == 0
    assert list(partners.items()) == []
    with pytest.raises(ValueError, match="key"):
        partners[0] = 0
