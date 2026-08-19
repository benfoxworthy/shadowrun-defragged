"""Fix melee instant-death bug.

When an armed character defends against melee, the game limits active-defense
dice to the smaller of the allocated Combat Pool and Melee skill. The relevant
logic is conceptually simple:

    melee = defender.melee_skill
    defense_dice = min(defense_dice, melee)

The implementation is not. Melee is an 8-bit value, but the 68000 instruction
that loads one byte changes only the low byte of its destination register. The
old high byte—left there by unrelated earlier work—survives. The next
instructions compare the entire 16-bit word. Instead of Melee 4, the routine
might see something like ``0xFF04``: a negative value whose later subtraction
can underflow into an enormous unsigned damage result. Wired Reflexes and
bare-handed attackers happen to produce the register history that made this
surface as an instant knockout.

Before:

    D7.low_byte = defender.melee_skill  # D7.high_byte remains stale
    if word(D7) < defense_dice:
        defense_dice = word(D7)

Patch: Extend the loaded byte before doing word arithmetic,
making the high byte a defined part of the skill value. There was no free room
at the bug site, so an equivalent nearby long conditional branch is shortened
to recover the two bytes needed for the extension. All branch destinations and
the intended ``min(pool, Melee)`` rule remain the same.

The original failure has been reproduced and confirmed fixed in-game. The exact
stale high-byte provenance is still not exhaustively reconstructed, but the
mixed-width error and the semantics of the repair are unambiguous.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "melee-instant-death-fix"
    description = (
        "Fixed a melee defense underflow bug that caused instant death when attacked in melee "
        "with Wired Reflexes or certain other cyberware installed."
    )
    category = "Gameplay Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Sign-extend the defense result so stale upper bits cannot survive.
        builder.replace(
            offset=0x055CEE,
            source_genesis_sum=48710,
            source_crc32_influence=0xEE7A5E11,
            payload=bytes.fromhex(
                "4887"  # CMP.W D6,D7 -> EXT.W D7
            ),
        )

        # Compare the cleaned defense result before deciding damage severity.
        builder.replace(
            offset=0x055CF0,
            source_genesis_sum=27136,
            source_crc32_influence=0x61F83883,
            payload=bytes.fromhex(
                "BE46"  # BPL.W $055CF6 -> CMP.W D6,D7
            ),
        )

        # Preserve the positive-result branch in the remaining two bytes.
        builder.replace(
            offset=0x055CF2,
            source_genesis_sum=4,
            source_crc32_influence=0x29CF9BA7,
            payload=bytes.fromhex(
                "6A02"  # branch extension -> BPL.S +2
            ),
        )


PATCH = Patch()
