"""Canonical, typed encoding for application-level vertex identifiers.

The encoded bytes are suitable as stable mapping keys. Each supported Python
type has a distinct one-byte tag, so values of different types never collide:
for example, ``1`` and ``"1"`` are different identities. Strings are encoded
as their exact UTF-8 representation without Unicode normalization. Consequently
canonically equivalent but byte-distinct Unicode strings remain distinct IDs.

Only exact ``str``, signed 64-bit exact ``int`` (excluding ``bool``), and exact
``uuid.UUID`` values are supported. The 4096-byte limit applies to the whole
encoded identifier, including its type tag. This module only defines identity
encoding; it does not assign IDs, persist mappings, or define vertex lifecycle.
"""

from __future__ import annotations

from uuid import UUID


class Identifier:
    """Encode and decode canonical typed identifiers."""

    Limit = 4096
    String = 1
    Integer = 2
    Uuid = 3
    Minimum = -(1 << 63)
    Maximum = (1 << 63) - 1

    @staticmethod
    def encode(value: str | int | UUID) -> bytes:
        """Return the deterministic, reversible byte encoding of ``value``.

        Args:
            value: An exact ``str``, signed 64-bit exact ``int``, or UUID.

        Raises:
            TypeError: If ``value`` has an unsupported type.
            ValueError: If the integer is out of range, the string cannot be
                encoded as UTF-8, or the encoded value exceeds 4096 bytes.
        """
        if type(value) is str:
            try:
                payload = value.encode("utf-8", errors="strict")
            except UnicodeEncodeError as error:
                raise ValueError("identifier string is not valid Unicode") from error
            result = bytes((Identifier.String,)) + payload
        elif type(value) is int:
            if not Identifier.Minimum <= value <= Identifier.Maximum:
                raise ValueError("identifier integer must fit signed 64-bit range")
            result = bytes((Identifier.Integer,)) + value.to_bytes(
                8, byteorder="big", signed=True
            )
        elif type(value) is UUID:
            result = bytes((Identifier.Uuid,)) + value.bytes
        else:
            raise TypeError("identifier must be an exact str, int, or uuid.UUID")

        if len(result) > Identifier.Limit:
            raise ValueError("encoded identifier exceeds 4096 bytes")
        return result

    @staticmethod
    def decode(value: bytes) -> str | int | UUID:
        """Decode a canonical identifier byte string.

        Args:
            value: An exact ``bytes`` object returned by :meth:`encode`.

        Raises:
            TypeError: If ``value`` is not exact ``bytes``.
            ValueError: If the bytes are oversized, malformed, or noncanonical.
        """
        if type(value) is not bytes:
            raise TypeError("encoded identifier must be exact bytes")
        if not value or len(value) > Identifier.Limit:
            raise ValueError("encoded identifier has invalid size")

        tag = value[0]
        payload = value[1:]
        if tag == Identifier.String:
            try:
                result = payload.decode("utf-8", errors="strict")
            except UnicodeDecodeError as error:
                raise ValueError("identifier string is not canonical UTF-8") from error
            if result.encode("utf-8") != payload:
                raise ValueError("identifier string is not canonical UTF-8")
            return result
        if tag == Identifier.Integer:
            if len(payload) != 8:
                raise ValueError("identifier integer must contain exactly 8 bytes")
            return int.from_bytes(payload, byteorder="big", signed=True)
        if tag == Identifier.Uuid:
            if len(payload) != 16:
                raise ValueError("identifier UUID must contain exactly 16 bytes")
            return UUID(bytes=payload)
        raise ValueError("identifier type tag is unknown")
