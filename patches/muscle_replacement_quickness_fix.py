"""Fix Muscle Replacement's displayed Quickness bonus.

The character sheet adds the cyberware rank to Quickness, but gameplay systems
read the unmodified base value: movement, the Quickness/Intelligence average
used for action speed and Matrix tests, Combat Pool, and the shared
party-Quickness helper used by scripted events. In practice, Muscle Replacement
only affected the Strength attribute.

Before:

    action_speed = average(base_quickness, Intelligence)
    combat_pool = average(base_quickness, Intelligence, Willpower)
    movement = movement_table[min(base_quickness, 9)]
    scripted_party_quickness = average(active_party.base_quickness)

    Eight scripted encounters consume the scripted_party_quickness calculation:
    running from Lone Star, several Corp Run random events, and hiding from a
    wilderness encounter.

Patch: A shared helper decodes ranks 1-4 from the character's cyberware bits
and returns base Quickness plus rank. The raw-Quickness reads call it before
continuing through their original formulas. The movement table has a soft cap
at effective Quickness 9, but ranks beyond it still improve action speed,
Combat Pool, Matrix tests, and scripted tests.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "muscle-replacement-quickness-fix"
    description = (
        "Fixed Muscle Replacement not affecting Quickness calculations. Modified Quickness is "
        "now used for movement speed, combat speed, combat success, and cybercombat success."
    )
    category = "Gameplay Bug Fixes"
    requires = ("defense-pip-display-clamp",)

    def build_patch(self, builder: PatchBuilder) -> None:
        # Return the character's total Quickness, including Muscle Replacement.
        #
        # quickness = actor.base_quickness
        # for level in 1..4:
        #     if actor.has_muscle_replacement(level):
        #         quickness += level
        #         break
        # The upward iteration is intentional and matches the game’s original
        # melee-power decoder. Only one bit should be set in a valid game state.
        muscle_replacement_quickness_helper_address = builder.add_cave(
            bytes.fromhex(
                "48E78300"  # MOVEM.L D0/D6-D7,-(A7)
                "4281"      # CLR.L D1
                "12280078"  # MOVE.B $78(A0),D1
                "30280090"  # MOVE.W $90(A0),D0
                "7E03"      # MOVEQ #3,D7
                "7C05"      # MOVEQ #5,D6
                "0D00"      # test_level: BTST.L D6,D0
                "6706"      # BEQ.S next_level
                "5946"      # SUBQ.W #4,D6
                "D246"      # ADD.W D6,D1
                "6006"      # BRA.S done
                "5246"      # next_level: ADDQ.W #1,D6
                "51CFFFF2"  # DBRA D7,test_level
                "4CDF00C1"  # done: MOVEM.L (A7)+,D0/D6-D7
                "4E75"      # RTS
            )
        )

        # The scripted party-Quickness helper iterates its actor in A3, while
        # the shared decoder above accepts it in A0. This adapter preserves
        # both address registers and performs the two displaced instructions.
        # All eight callers overwrite or ignore D1 after the shared helper;
        # the stock helper's meaningful output is the D6 dice pool.
        scripted_quickness_accumulator_address = builder.add_cave(
            bytes.fromhex(
                "C14B"      # EXG A0,A3
                "4EB9"      # JSR effective_Quickness(A0)
                f"{muscle_replacement_quickness_helper_address}"
                "C14B"      # EXG A0,A3
                "DC01"      # ADD.B D1,D6
                "5200"      # ADDQ.B #1,D0
                "4E75"      # RTS
            )
        )

        # Use total Quickness in the shared Quickness/Intelligence average for
        # action speed and Matrix power tests.
        builder.replace(
            offset=0x00D81C,
            source_genesis_sum=21793,
            source_crc32_influence=0x7E3D90F7,
            payload=bytes.fromhex(
                "4EB9"  # JSR absolute-long
                f"{muscle_replacement_quickness_helper_address}"
            ),
        )

        # Use total Quickness before Combat Pool adds Intelligence and Willpower.
        builder.replace(
            offset=0x055ED6,
            source_genesis_sum=21793,
            source_crc32_influence=0x7900ECDF,
            payload=bytes.fromhex(
                "4EB9"  # JSR absolute-long
                f"{muscle_replacement_quickness_helper_address}"
            ),
        )

        # Use total Quickness before the existing movement cap and table lookup.
        builder.replace(
            offset=0x00B648,
            source_genesis_sum=23329,
            source_crc32_influence=0x1E73BA78,
            payload=bytes.fromhex(
                "4EB9"  # JSR absolute-long
                f"{muscle_replacement_quickness_helper_address}"
            ),
        )

        # Modify each active member's Quickness before the shared helper
        # divides the party total. This covers actions 153, 212, 215, 216,
        # 219, 220, 224, and 238.
        builder.replace(
            offset=0x02376E,
            source_genesis_sum=77475,
            source_crc32_influence=0xD318C1A8,
            payload=bytes.fromhex(
                "4EB9"  # JSR absolute-long
                f"{scripted_quickness_accumulator_address}"
            ),
        )


PATCH = Patch()
