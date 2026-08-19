"""Make Agira's Notebook correctly list the Power Focus 4

Agira's notebook entry says "Power Focus 3", but it's actually a Power Focus 4.
This contradiction has two reasonable solutions. This is the presentation-only
choice that preserves the more-powerful Rank 4 item.

Before: The Contacts entry says ``Offers Lvl 3 Power Focus``, while Agira's
purchase action creates the item at rank 4.

Patch: Change the displayed ``3`` to ``4``. This conflicts with
``agira-power-focus-rank-3``, which makes the opposite design choice.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "agira-power-focus-notebook-rank-4"
    description = (
        "The Contacts entry for Agira Tetsumi now correctly says \"Offers Lvl 4 Power Focus\" "
        "instead of \"Lvl 3\"."
    )
    category = "UI/Display Bug Fixes"
    conflicts = ("agira-power-focus-rank-3",)

    def build_patch(self, builder: PatchBuilder) -> None:
        # Correct the Power Focus rank shown in Agira's Notebook entry.
        builder.replace(
            offset=0x0C637B,
            source_genesis_sum=51,
            source_crc32_influence=0x5586B4F7,
            payload=bytes.fromhex(
                "34"  # ASCII '3' -> '4' in the existing encoded Notebook text stream
            ),
        )


PATCH = Patch()
