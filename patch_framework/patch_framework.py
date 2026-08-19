"""Framework for authoritative, executable patch definitions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import ClassVar
import zlib


class Address(int):
    """A numeric ROM address that defaults to eight hexadecimal digits."""

    def __new__(cls, value: int) -> "Address":
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"address must be an integer, got {type(value).__name__}")
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError(f"address is outside the 32-bit range: {value}")
        return super().__new__(cls, value)

    def __format__(self, format_spec: str) -> str:
        return int.__format__(self, format_spec or "08X")


@dataclass(frozen=True)
class PreimageGuard:
    """Non-literal metadata for one source-ROM byte range."""

    genesis_sum: int
    crc32_influence: int

    def __post_init__(self) -> None:
        if self.genesis_sum < 0:
            raise ValueError("preimage Genesis sum cannot be negative")
        if not 0 <= self.crc32_influence <= 0xFFFFFFFF:
            raise ValueError("preimage CRC-32 influence is outside 32 bits")

    @classmethod
    def from_bytes(
        cls, offset: int, source: bytes, rom_size: int
    ) -> "PreimageGuard":
        return cls(
            genesis_sum=sum(
                byte * (0x100 if (offset + index) % 2 == 0 else 1)
                for index, byte in enumerate(source)
            ),
            crc32_influence=crc32_influence(offset, source, rom_size),
        )


@lru_cache(maxsize=None)
def crc32_influence(offset: int, data: bytes, rom_size: int) -> int:
    """Return the affine CRC-32 influence of sparse bytes at ``offset``."""

    end = offset + len(data)
    if offset < 0 or end > rom_size:
        raise ValueError("CRC-32 influence range lies outside the ROM")
    sparse = bytearray(rom_size)
    sparse[offset:end] = data
    zero_crc = zlib.crc32(bytes(rom_size)) & 0xFFFFFFFF
    return (zlib.crc32(sparse) & 0xFFFFFFFF) ^ zero_crc


@dataclass(frozen=True)
class Edit:
    """One fully resolved, length-preserving ROM edit."""

    offset: int
    preimage: PreimageGuard
    payload: bytes
    patch_id: str = ""


GAME_GENIE_ALPHABET = "ABCDEFGHJKLMNPRSTVWXYZ0123456789"
GAME_GENIE_HARDWARE_LIMIT = 5


def encode_game_genie_code(address: int, value: int) -> str:
    """Encode one aligned 16-bit ROM replacement as a Game Genie code."""

    if not isinstance(address, int) or isinstance(address, bool):
        raise TypeError("Game Genie address must be an integer")
    if not 0 <= address <= 0xFFFFFF:
        raise ValueError("Game Genie address is outside the 24-bit range")
    if address % 2:
        raise ValueError("Game Genie address must be 16-bit aligned")
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("Game Genie replacement must be an integer")
    if not 0 <= value <= 0xFFFF:
        raise ValueError("Game Genie replacement is outside the 16-bit range")

    character_values = (
        (value >> 3) & 0x1F,
        ((value & 0x07) << 2) | ((address >> 14) & 0x03),
        (address >> 9) & 0x1F,
        ((address >> 20) & 0x0F) | (((address >> 8) & 0x01) << 4),
        (((address >> 16) & 0x0F) << 1) | ((value >> 12) & 0x01),
        ((value >> 15) & 0x01) | (((value >> 8) & 0x0F) << 1),
        ((address >> 5) & 0x07) | (((value >> 13) & 0x03) << 3),
        address & 0x1F,
    )
    encoded = "".join(
        GAME_GENIE_ALPHABET[index] for index in character_values
    )
    return f"{encoded[:4]}-{encoded[4:]}"


def game_genie_codes_for_edits(
    edits: Iterable[Edit],
) -> tuple[str, ...] | None:
    """Return codes when all edits fit one original five-code device.

    Genesis Game Genie substitutions operate on aligned 16-bit ROM words.
    Returning ``None`` keeps partial-word and oversized edit plans out of the
    patch listing instead of presenting an incomplete hardware patch.
    """

    codes: list[str] = []
    for edit in edits:
        if edit.offset % 2 or len(edit.payload) % 2:
            return None
        for index in range(0, len(edit.payload), 2):
            if len(codes) == GAME_GENIE_HARDWARE_LIMIT:
                return None
            codes.append(
                encode_game_genie_code(
                    edit.offset + index,
                    int.from_bytes(edit.payload[index : index + 2], "big"),
                )
            )
    return tuple(codes) or None


@dataclass(frozen=True)
class CaveAllocation:
    """One resolved block allocated from the configured ROM code cave."""

    patch_id: str
    address: Address
    size: int


@dataclass
class _BuildState:
    cave_start: int
    cave_end: int
    cursor: int
    cave_preimage: PreimageGuard | None
    cave_payload: bytearray
    edits: list[Edit] = field(default_factory=list)
    allocations: list[CaveAllocation] = field(default_factory=list)


class PatchBuilder:
    """Record one or more patches without requiring or modifying a ROM."""

    def __init__(
        self,
        cave_start: int | None = None,
        cave_end: int | None = None,
        *,
        cave_preimage: PreimageGuard | None = None,
        cave_fill: int = 0xFF,
        _state: _BuildState | None = None,
        _patch_id: str = "",
    ) -> None:
        if _state is None:
            if cave_start is None or cave_end is None:
                raise TypeError("root PatchBuilder requires cave_start and cave_end")
            if cave_start < 0 or cave_end < cave_start:
                raise ValueError("invalid code-cave range")
            if not 0 <= cave_fill <= 0xFF:
                raise ValueError("code-cave fill byte is outside 8 bits")
            _state = _BuildState(
                cave_start,
                cave_end,
                cave_start,
                cave_preimage,
                bytearray([cave_fill]) * (cave_end + 1 - cave_start),
            )
        self._state = _state
        self._patch_id = _patch_id

    def for_patch(self, patch_id: str) -> "PatchBuilder":
        """Return a view that records operations as the given patch."""

        if not patch_id:
            raise ValueError("patch ID cannot be empty")
        return PatchBuilder(_state=self._state, _patch_id=patch_id)

    @property
    def edits(self) -> list[Edit]:
        edits = list(self._state.edits)
        if self._state.allocations:
            if self._state.cave_preimage is None:
                raise RuntimeError("allocated code cave has no source preimage guard")
            edits.append(
                Edit(
                    patch_id="code-cave",
                    offset=self._state.cave_start,
                    preimage=self._state.cave_preimage,
                    payload=bytes(self._state.cave_payload),
                )
            )
        return edits

    @property
    def allocations(self) -> list[CaveAllocation]:
        return list(self._state.allocations)

    def add_cave(
        self,
        payload: bytes,
        *,
        alignment: int = 2,
    ) -> Address:
        """Allocate payload bytes within the configured replacement cave."""

        self._require_patch_scope()
        self._validate_bytes(payload, "cave payload")
        if alignment <= 0 or alignment & (alignment - 1):
            raise ValueError(
                f"cave alignment must be a positive power of two, got {alignment}"
            )

        cursor = (self._state.cursor + alignment - 1) & -alignment
        end = cursor + len(payload)
        if end - 1 > self._state.cave_end:
            required = end - self._state.cave_start
            available = self._state.cave_end + 1 - self._state.cave_start
            raise ValueError(
                f"selected cave blocks need {required} bytes; "
                f"the configured code cave has {available}"
            )

        address = Address(cursor)
        self._state.cursor = end
        self._state.allocations.append(
            CaveAllocation(
                patch_id=self._patch_id,
                address=address,
                size=len(payload),
            )
        )
        payload_offset = address - self._state.cave_start
        self._state.cave_payload[payload_offset : payload_offset + len(payload)] = (
            payload
        )
        return address

    def rewrite_cave(self, address: int, payload: bytes) -> None:
        """Finalize bytes inside one cave allocation owned by this patch.

        This is intentionally narrower than ``replace``: it may only rewrite
        bytes already allocated by the current patch.  It exists for
        post-build fixups whose values depend on the complete selected edit
        plan, such as a build fingerprint embedded by a finalizer.
        """

        self._require_patch_scope()
        self._validate_bytes(payload, "cave rewrite")
        end = address + len(payload)
        allocation = next(
            (
                item
                for item in self._state.allocations
                if item.patch_id == self._patch_id
                and item.address <= address
                and end <= item.address + item.size
            ),
            None,
        )
        if allocation is None:
            raise ValueError(
                "cave rewrite must stay inside an allocation owned by "
                f"{self._patch_id}"
            )
        payload_offset = address - self._state.cave_start
        self._state.cave_payload[payload_offset : payload_offset + len(payload)] = (
            payload
        )

    def replace(
        self,
        *,
        offset: int,
        source_genesis_sum: int,
        source_crc32_influence: int,
        payload: bytes,
    ) -> None:
        """Record one fixed-location ROM replacement."""

        self._require_patch_scope()
        self._validate_bytes(payload, "replacement payload")
        preimage = PreimageGuard(
            genesis_sum=source_genesis_sum,
            crc32_influence=source_crc32_influence,
        )
        self._state.edits.append(
            Edit(
                patch_id=self._patch_id,
                offset=offset,
                preimage=preimage,
                payload=payload,
            )
        )

    def _require_patch_scope(self) -> None:
        if not self._patch_id:
            raise RuntimeError("record edits through builder.for_patch(patch_id)")

    @staticmethod
    def _validate_bytes(value: bytes, name: str) -> None:
        if not isinstance(value, bytes):
            raise TypeError(f"{name} must be bytes")
        if not value:
            raise ValueError(f"{name} cannot be empty")


class PatchSpec(ABC):
    """Metadata and executable build method for one selectable patch."""

    id: ClassVar[str]
    description: ClassVar[str]
    category: ClassVar[str] = ""
    requires: ClassVar[tuple[str, ...]] = ()
    conflicts: ClassVar[tuple[str, ...]] = ()
    finalize_priority: ClassVar[int] = 0

    @abstractmethod
    def build_patch(self, builder: PatchBuilder) -> None:
        """Record this patch's cave allocations and fixed-location edits."""

    def finalize_patch(self, builder: PatchBuilder) -> None:
        """Apply fixups after every selected patch has recorded its edits."""
