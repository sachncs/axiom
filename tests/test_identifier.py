"""Tests for canonical application identifier encoding."""

from uuid import UUID

import pytest

from axiom.identifier import Identifier


@pytest.mark.parametrize(
    "value",
    [
        "",
        "plain text",
        "é",
        "e\u0301",
        "\x00",
        "x" * (Identifier.Limit - 1),
        0,
        1,
        -1,
        Identifier.Minimum,
        Identifier.Maximum,
        UUID("00112233-4455-6677-8899-aabbccddeeff"),
    ],
)
def test_encoding_round_trips_exact_supported_values(value: str | int | UUID) -> None:
    encoded = Identifier.encode(value)

    assert type(encoded) is bytes
    assert len(encoded) <= Identifier.Limit
    assert Identifier.decode(encoded) == value
    assert Identifier.encode(Identifier.decode(encoded)) == encoded


def test_strings_preserve_distinct_unicode_sequences_without_normalization() -> None:
    composed = Identifier.encode("é")
    decomposed = Identifier.encode("e\u0301")

    assert composed != decomposed
    assert Identifier.decode(composed) == "é"
    assert Identifier.decode(decomposed) == "e\u0301"


def test_type_tags_prevent_cross_type_collisions() -> None:
    values: list[str | int | UUID] = [1, "1", UUID(int=1)]

    assert len({Identifier.encode(value) for value in values}) == len(values)


@pytest.mark.parametrize("value", [True, False, 1.0, b"1", bytearray(b"1"), None])
def test_encoding_rejects_unsupported_types(value: object) -> None:
    with pytest.raises(TypeError):
        Identifier.encode(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [-(1 << 63) - 1, 1 << 63])
def test_encoding_rejects_integers_outside_signed_64_bit_range(value: int) -> None:
    with pytest.raises(ValueError, match="signed 64-bit"):
        Identifier.encode(value)


def test_encoding_rejects_invalid_surrogate_and_oversized_string() -> None:
    with pytest.raises(ValueError, match="valid Unicode"):
        Identifier.encode("\ud800")
    with pytest.raises(ValueError, match="4096 bytes"):
        Identifier.encode("x" * Identifier.Limit)


@pytest.mark.parametrize(
    "encoded",
    [
        b"",
        b"\xff",
        b"\x01\xc0\xaf",
        b"\x01\xed\xa0\x80",
        b"\x02",
        b"\x02" + bytes(7),
        b"\x02" + bytes(9),
        b"\x03",
        b"\x03" + bytes(15),
        b"\x03" + bytes(17),
        b"\x01" + bytes(Identifier.Limit),
    ],
)
def test_decoding_rejects_malformed_or_oversized_encodings(encoded: bytes) -> None:
    with pytest.raises(ValueError):
        Identifier.decode(encoded)


@pytest.mark.parametrize("encoded", [bytearray(b"\x01x"), memoryview(b"\x01x")])
def test_decoding_requires_exact_bytes(encoded: object) -> None:
    with pytest.raises(TypeError, match="exact bytes"):
        Identifier.decode(encoded)  # type: ignore[arg-type]
