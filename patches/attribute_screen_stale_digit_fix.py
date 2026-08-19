"""Clear the stale ``1`` left behind when switching characters on the
Attributes/Skills screen.

Attribute numbers are drawn right-to-left, so the tens digit of ``10`` sits
one tile beyond the character-switch clear rectangle. A later one-digit value
redraws only the normal cell and leaves that ``1`` behind. This could cause
a rendering artifact when one character had an Attribute above 10 (e.g.
Winston)

Before:

    draw_number(value, rightmost_tile)  # tens digit goes one tile left
    clear_on_switch(starts_two_tiles_to_the_right)

Patch: Move the clear rectangle two tiles left and widen it by two. This keeps
its original right edge while covering both digits and the augmented-value
cells.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "attribute-screen-stale-digit-fix"
    description = (
        "Fixed a stuck \"1\" rendered on the Attributes/Skills screen when switching characters "
        "after viewing an attribute of 10 or higher."
    )
    category = "UI/Display Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Move the character-switch clear rectangle left over the tens digit.
        builder.replace(
            offset=0x00D4CC,
            source_genesis_sum=50084,
            source_crc32_influence=0x9D2BDABA,
            payload=bytes.fromhex(
                "C3A0"  # MOVE.L #$0000C3A4,D4 -> MOVE.L #$0000C3A0,D4
            ),
        )

        # Widen the rectangle while preserving its original right edge.
        builder.replace(
            offset=0x00D4D4,
            source_genesis_sum=3,
            source_crc32_influence=0x58F99A05,
            payload=bytes.fromhex(
                "0005"  # MOVE.W #3,D7 -> MOVE.W #5,D7
            ),
        )


PATCH = Patch()
