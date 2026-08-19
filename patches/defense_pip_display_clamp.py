"""Keep defense displays within their 22-entry pip graphics tables.

Combat values above 22 remain valid. Only the zero-based graphics-table index
is clamped, preventing the renderers from reading unrelated ROM data.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "defense-pip-display-clamp"
    description = (
        "Fix corrupted graphics in the various Defense UIs when the user's defense "
        "value exceeds the number of pips on screen; the value clamps instead."
    )
    category = "UI/Display Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Convert a displayed value into the safe zero-based table index used
        # by all three renderers: clamp(value - 1, 0, 21).
        clamp_defense_pip_index_address = builder.add_cave(
            bytes.fromhex(
                "5346"      # SUBQ.W #1,D6
                "6A04"      # BPL.S nonnegative
                "4286"      # CLR.L D6
                "4E75"      # RTS
                "0C460015"  # nonnegative: CMPI.W #21,D6
                "6302"      # BLS.S done
                "7C15"      # MOVEQ #21,D6
                "4E75"      # done: RTS
            )
        )

        hook = bytes.fromhex(
            "4EB9"  # JSR absolute-long
            f"{clamp_defense_pip_index_address}"
            "4E71"  # NOP padding over the displaced lower-bound sequence
        )

        # Spell-menu physical/mental defense preview.
        builder.replace(
            offset=0x0105B6,
            source_genesis_sum=65488,
            source_crc32_influence=0xAC5FAF75,
            payload=hook,
        )

        # Character-sheet physical/mental spell defense.
        builder.replace(
            offset=0x010706,
            source_genesis_sum=65488,
            source_crc32_influence=0x37E78F74,
            payload=hook,
        )

        # Character-sheet physical Defense.
        builder.replace(
            offset=0x012E7A,
            source_genesis_sum=65488,
            source_crc32_influence=0x00C30B6C,
            payload=hook,
        )


PATCH = Patch()
