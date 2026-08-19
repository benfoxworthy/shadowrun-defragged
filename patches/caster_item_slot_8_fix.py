"""Fix Spell Foci, Power Foci, and Fetishes ignoring the bottom-right inventory slot.

Several inventory scans related to spell caster items would skip the last
inventory slot. That meant bonuses from Spell Foci or Power Foci in Slot 8
would never apply, and Fetishes in that slot would never get used.

Shamans have a permanent Totem in that slot (which is the likely reason for
this oversight) - the bug can only apply to the two Mages, Trent and Freya.

Before:
Each of the three independent item scans used the same loop bounds:

    for (int slot = 6; slot >= 0; slot--) {  // scans seven of eight slots
        /* item-specific check */
    }

Patch: Start all three existing loops at slot 7. Their matching, charge, and
rating rules remain unchanged. The shared Spell Focus/Totem loop begins at
`0x0104F6`; Totems already use their dedicated eighth slot separately.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "caster-item-slot-8-fix"
    description = (
        "Fixed Spell Foci, Power Foci, and Fetishes not working when placed in"
        " Inventory Slot 8, the bottom-right slot."
    )
    category = "Gameplay Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Extend post-cast Fetish drain absorption through the final slot.
        builder.replace(
            offset=0x01042C,
            source_genesis_sum=32262,
            source_crc32_influence=0x78CEF606,
            payload=bytes.fromhex(
                "7E07"  # MOVEQ #6,D7 -> MOVEQ #7,D7
            ),
        )

        # Extend the Focus inventory scan through the eighth and final slot.
        builder.replace(
            offset=0x0104F8,
            source_genesis_sum=30726,
            source_crc32_influence=0x206BDEC7,
            payload=bytes.fromhex(
                "7807"  # MOVEQ #6,D4 -> MOVEQ #7,D4
            ),
        )

        # Extend the stock Power Focus inventory scan through the final slot.
        # power-focus-rework retires this loop at its next instruction, avoiding
        # an overlapping edit when both patches are selected.
        builder.replace(
            offset=0x055F08,
            source_genesis_sum=32262,
            source_crc32_influence=0x6BBA20D6,
            payload=bytes.fromhex(
                "7E07"  # MOVEQ #6,D7 -> MOVEQ #7,D7
            ),
        )


PATCH = Patch()
