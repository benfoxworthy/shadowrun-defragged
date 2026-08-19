"""Make Power Focus actually work like a universal Spell Focus.

Gregory Wilns calls Power Focus “much like a spell focus, with one exception:
it increases the power of ANY spell.” However, it didn't work like a Spell
Focus.

A Spell Focus adds its rank directly to spell cast tests as additional casting
dice. The Power Focus instead added its rank to the caster's **Sorcery
skill**. That's a major difference, because unlike Firearms/Melee, the Sorcery
skill doesn't directly add to spell cast dice. Instead, it works more like the
Combat Pool, where the dice are distributed between offense and drain
resistance according to the caster's Stance slider. Importantly, the effect of
this pool is capped by the user's Magic score (a max of 6) - which meant that
most of the offensive benefit of the Power Focus is lost.

Instead, the Power Focus mostly affected two things: (1) Drain resistance
(because the defensive share of "effective Sorcery" feeds into that), and (2)
the party's shared magical defense stat (see 'sorcery_tooltip.py').

This design is unintuitive, makes the Power Focus almost useless in the late
game (since Drain isn't much of a concern and its effect on defense is
minimal), and arguably a bug since it doesn't match the in-game description
from Gregory.

This patch makes Power Focus work as advertised, directly adding dice to the
spell-casting test, like a Spell Focus. This means it now significantly affects
spell offense for all spells, as you'd expect. Only the highest-ranked Spell
Focus or Power Focus is used.

Before:

    effective_sorcery = Sorcery + PowerFocus.rank
    offense_pool = floor(effective_sorcery * stance_setting / 4)
    drain_pool = Willpower + effective_sorcery - offense_pool
    party_magic_defense += floor((effective_sorcery + 1) / 4)

    casting_dice = Force + min(Magic, offense_pool)
    casting_dice += matching_SpellFocus.rank

At full allocation, Sorcery 6 and Magic 6 already supply the maximum six
offensive Sorcery dice, so a Power Focus has no offensive effect.

Patch: Remove Power Focus from effective Sorcery and fold it into the later
Focus scan. Each inventory slot may contribute either the selected spell's
matching Focus or the universal Power Focus; the scan remembers the highest
eligible rank and adds it exactly once:

    effective_sorcery = Sorcery
    casting_dice += max(matching_SpellFocus.rank, PowerFocus.rank)

This prevents stacking while making inventory order irrelevant, and preserves
the existing Totem calculation. Drain and shared defense now depend on actual
Sorcery alone.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "power-focus-rework"
    description = (
        "Power Focus now adds dice directly to the spell-casting test, like a Spell Focus, "
        "instead of increasing effective Sorcery. Its effect is no longer scaled by "
        "stance or capped by Magic and no longer affects drain resistance or shared "
        "party spell defense. Only the highest-ranked Spell Focus or Power Focus is used."
    )
    category = "Gameplay Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Replacement for the stock Spell Focus scan: Consider both Power Foci
        # and matching Spell Foci, track the max rating, and add it to casting
        # dice.
        add_highest_focus_rank_address = builder.add_cave(
            bytes.fromhex(
                "7807"          # MOVEQ #7,D4 (all eight inventory slots)
                "4280"          # CLR.L D0 (maximum Focus rank)
                "BA304066"      # scan_slot: CMP.B $66(A0,D4.W),D5
                "6708"          # BEQ.S eligible
                "0C3000184066"  # CMPI.B #$18,$66(A0,D4.W)
                "660A"          # BNE.S next_slot
                "B030406E"      # eligible: CMP.B $6E(A0,D4.W),D0
                "6404"          # BCC.S next_slot (maximum >= candidate)
                "1030406E"      # MOVE.B $6E(A0,D4.W),D0
                "51CCFFE6"      # next_slot: DBRA D4,scan_slot
                "DC00"          # ADD.B D0,D6
                "4E75"          # RTS
            )
        )

        # Remove Power Focus from "effective Sorcery" calculation
        # Return from subroutine after its slot-counter initialization
        # so this edit does not overlap caster-item-slot-8-fix at $055F08.
        builder.replace(
            offset=0x055F0A,
            source_genesis_sum=3120,
            source_crc32_influence=0xEE0CDE79,
            payload=bytes.fromhex(
                "4E75"  # CMPI.B #$18,$66(A0,D7.W) -> RTS
            ),
        )

        # Replace the 20-byte stock Spell Focus loop with a call to the unified
        # cave scan. Returning falls through to the untouched Totem checks.
        builder.replace(
            offset=0x0104FA,
            source_genesis_sum=274174,
            source_crc32_influence=0x0B14369A,
            payload=bytes.fromhex(
                "4EB9"                      # JSR absolute-long
                f"{add_highest_focus_rank_address:08X}"
                "4E714E714E714E714E714E714E71"  # NOP Retired Spell Focus scan
            ),
        )


PATCH = Patch()
