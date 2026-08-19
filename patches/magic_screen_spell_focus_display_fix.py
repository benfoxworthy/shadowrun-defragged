"""Fix second-row Magic-screen previews using the incorrect Spell Focus.

The menu contains seven spells per row, but the Success-pip calculation used a
row stride of six. Every spell on the second row therefore looked for the Spell
Focus matching the spell immediately before it - causing the previewed
calculation to be incorrect. Casting was unaffected because combat derives the
Spell Focus from the equipped spell rather than the menu cursor.

Before:

    preview_spell_index = menu_row * 6 + menu_column  # seven-column menu
    preview_dice += matching_focus_rank(preview_spell_index)

Patch: Change the row stride from six to seven. The Focus scan and actual
casting formulas remain untouched.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "magic-screen-spell-focus-display-fix"
    description = (
        "Fixed spells in the bottom row of the Magic screen calculating the Success pips using "
        "the Spell Focus for the wrong spell. This was a display issue only; these spells did "
        "use the correct Spell Focus when casting."
    )
    category = "UI/Display Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Use the screen's actual seven-spell row stride for Focus lookup.
        builder.replace(
            offset=0x0104D0,
            source_genesis_sum=49410,
            source_crc32_influence=0x73C4DB09,
            payload=bytes.fromhex(
                "C0FC0007"  # MULU.W #$0006,D0 -> MULU.W #$0007,D0
            ),
        )


PATCH = Patch()
