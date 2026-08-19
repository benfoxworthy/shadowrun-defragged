"""Apply Lone Star escape penalties to the intended armor types.

Dialogue action 153 raises the target number for running from Lone Star based
on Joshua's equipped-armor ID. The stock comparisons use IDs 5 and 6:

    target = 4
    if (joshua.armor == 5)  // Lined Duster
        target += 1
    if (joshua.armor == 6)  // Light Combat Armor
        target += 2

That yields target numbers 5, 6, and 4 for the Lined Duster, Light Combat
Armor, and Heavy Combat Armor respectively. The Lined Duster should not hinder
escape, while the heavier armor should. Shift the compared IDs by one, leaving
the existing +1 and +2 adjustments intact:

    target = 4
    if (joshua.armor == 6)  // Light Combat Armor
        target += 1
    if (joshua.armor == 7)  // Heavy Combat Armor
        target += 2

The routine intentionally consults Joshua's armor only, despite rolling the
active party's average Quickness; changing that stock asymmetry is outside this
targeted bug fix.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "lone-star-escape-armor-fix"
    description = (
        "Fixed Lone Star escape penalties applying to the Lined Duster instead of "
        "Heavy Combat Armor."
    )
    category = "Gameplay Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Armor ID 6 is Light Combat Armor, which receives the existing +1 TN.
        builder.replace(
            offset=0x0237A5,
            source_genesis_sum=5,
            source_crc32_influence=0x30A8D6BA,
            payload=bytes.fromhex("06"),  # CMPI.B #$05 -> #$06
        )

        # Armor ID 7 is Heavy Combat Armor, which receives the existing +2 TN.
        builder.replace(
            offset=0x0237B3,
            source_genesis_sum=6,
            source_crc32_influence=0x35923A48,
            payload=bytes.fromhex("07"),  # CMPI.B #$06 -> #$07
        )


PATCH = Patch()
