"""Prevent Rockskin with Heavy Combat Armor completely negating Ballistic damage

Firearm damage is capped at 10 before armor. Heavy Combat Armor subtracts 8,
and the repaired Rockskin effect later subtracts another 2. Their combination
therefore erases the maximum possible firearm hit, regardless of attack rolls.

Before:

    damage = min(damage, 10)
    damage -= ballistic_armor       # Heavy Combat Armor: -8
    damage -= 2 if Rockskin else 0  # combined protection: 10

Patch: Cap only this combination at 9. When Rockskin is active and ballistic
armor is at least 8, credit one damage box before the normal armor subtraction;
the unchanged Rockskin step then produces nine total protection. Lower armor,
other damage types, and the displayed armor value remain untouched.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "rockskin-ballistic-armor-cap"
    description = (
        "Rockskin can no longer raise effective Ballistic Armor above 9, preventing Heavy "
        "Combat Armor plus Rockskin from granting complete immunity to ballistic damage."
    )
    category = "Balance Improvements"
    requires = ("rockskin-and-talisman-defense-fix",)

    def build_patch(self, builder: PatchBuilder) -> None:
        # Subtract armor while capping armor plus Rockskin at nine points.
        #
        # if defender.has_rockskin and ballistic_armor >= 8:
        #     staged_damage += 1  // preserve displayed armor; offset the later
        #                         // shared Rockskin subtraction by one
        #     // (damage + 1) - armor == damage - (armor - 1)
        # staged_damage -= ballistic_armor
        #
        # Adjust staged damage in D5 rather than the armor value in D0. The
        # armor-stat renderer shares this routine and expects D0 to remain the
        # character's real displayed armor.
        rockskin_ballistic_cap_helper_address = builder.add_cave(
            bytes.fromhex(
                "10341025"      # MOVE.B $25(A4,D1.W),D0
                "082900050011"  # BTST #5,$11(A1) (defender Rockskin)
                "6708"          # BEQ.S subtract_armor
                "0C000008"      # CMPI.B #8,D0
                "6502"          # BCS.S subtract_armor
                "5205"          # ADDQ.B #1,D5 (credit the cap)
                "9A00"          # subtract_armor: SUB.B D0,D5
                "4E75"          # RTS
            )
        )

        # Replace the stock armor subtraction with the Rockskin-aware capped value.
        builder.replace(
            offset=0x055EAA,
            source_genesis_sum=47705,
            source_crc32_influence=0x8DEFCD81,
            payload=bytes.fromhex(
                "4EB9"  # JSR absolute-long
                f"{rockskin_ballistic_cap_helper_address}"
            ),
        )


PATCH = Patch()
