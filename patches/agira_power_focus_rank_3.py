"""Make Agira sell the Rank 3 Power Focus advertised in the Notebook.
DISABLED BY DEFAULT

In the original game, Power Focus barely helped offensive casting: it raised
effective Sorcery, but the spell formula capped the usable Sorcery pool at
Magic. The companion ``power-focus-rework`` makes it behave intuitively by
adding its rank directly to every spell's success dice.

That fix also makes the rank-4 Power Focus extremely strong. It supplies four
uncapped dice to every spell, including Mana Bolt, Mana Blast, Flame Dart, and
Flame Bolt—the bread-and-butter single-target damage spells for which the game
offers no obtainable matching Spell Focus. Reducing Agira's item to rank 3 is
a modest balancing counterweight and, conveniently, makes the purchase agree
with the original Contacts note.

Despite this logic, I disabled this patch by default and adjusted the notebook
text instead because it's more fun to blow things up! But this is probably
more balanced.

Before: Agira's purchase action effectively does:

    inventory[empty_slot] = PowerFocus(rank=4)

The Notebook says level 3. In the stock casting formula the Focus bonus is
usually swallowed by ``min(Magic, effective Sorcery)``; with
``power-focus-rework`` it becomes four direct success dice for every spell.

Patch: Store rank 3 instead of rank 4. Choose this or
``agira-power-focus-notebook-rank-4``, which preserves the stronger item and
corrects the Notebook instead.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "agira-power-focus-rank-3"
    description = (
        "Alternative to agira-power-focus-notebook-rank-4: the Power Focus sold by Agira "
        "Tetsumi is now Rank 3 instead of Rank 4. This matches the note in the Contacts page of "
        "the Notebook and brings it in line with most obtainable Spell Foci."
    )
    category = "Disabled Patches"
    conflicts = ("agira-power-focus-notebook-rank-4",)

    def build_patch(self, builder: PatchBuilder) -> None:
        # Make Agira grant a rank-3 Power Focus instead of rank 4.
        builder.replace(
            offset=0x024A9A,
            source_genesis_sum=61340,
            source_crc32_influence=0x27174C21,
            payload=bytes.fromhex(
                "17BC00186000"  # MOVE.B #$18,$0(A3,D6.W) (Power Focus ID)
                "17BC00036008"  # MOVE.B #3,$8(A3,D6.W) (rank)
            ),
        )


PATCH = Patch()
