"""Make Lone Star Heat worsen its initial Charisma check.

During dialogue action 150, the initial Lone Star encounter rolls a value
from 0 through 11 and compares it with Joshua's Charisma. Stock code subtracts
Heat from that roll, which makes every point of Heat make the encounter easier
to pass:

    roll = randomBelow(12)
    success = (roll - heat) <= Joshua.charisma

Heat is the party's wanted level, so its effect is plainly inverted. Change
the arithmetic to addition while retaining the existing range, comparison, and
success path (including the separate Heat reduction after a successful check):

    roll = randomBelow(12)
    success = (roll + heat) <= Joshua.charisma

This is a one-instruction, in-place repair. Later Lone Star dialogue actions
use their own checks and are deliberately unaffected.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "lone-star-heat-check-fix"
    description = (
        "Fixed Lone Star Heat making the initial Charisma check easier instead of harder."
    )
    category = "Gameplay Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        builder.replace(
            offset=0x02348C,
            source_genesis_sum=36864,
            source_crc32_influence=0x8559D9C2,
            payload=bytes.fromhex("D0"),  # SUB.B Heat,D0 -> ADD.B Heat,D0
        )


PATCH = Patch()
