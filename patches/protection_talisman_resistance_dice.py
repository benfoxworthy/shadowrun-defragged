"""Make Protection Talisman work like Resistance Dice instead of like Armor.

With the attacker/defender bug fixed (see 'rockskin_and_talisman_defense_fix'),
the Protection Talisman provides a flat subtraction to every damage type,
similar to Armor. This had three design problems:
 1. Integer division makes ranks 2 and 3 identical
 2. Rank 4 plus Heavy Combat Armor can make the character fully immune to all
    firearm damage, which seems too powerful and unintended.
 3. Rockskin also applies a flat damage reduction, and they do not stack, making
    Rockskin pointless to cast on a character with a Protection Talisman Rank 4.

This patch reworks the Protection Talisman to instead add resistance dice, like
Body or Willpower, which is intuitive and fixes all three problems cleanly.

Note: Rockskin has the same problem #2, but is fixed separately - see
'rockskin_ballistic_armor_cap'

Before:

    damage -= floor(ProtectionTalisman.rank / 2)
    # skipped entirely when Rockskin is active

Patch: Treat the full rank as resistance dice, like Body or Willpower:

    resistance_dice += ProtectionTalisman.rank

The existing inventory scan is called before firearm/grenade/spell and melee
resistance rolls; its later flat subtraction is removed. Dice make rank 3
meaningfully better than rank 2 without guaranteeing immunity, and Rockskin
can retain its separate two-box effect. This patch requires
``rockskin-and-talisman-defense-fix`` so the scan uses the defender's inventory.

The physical Defense value and both spell-defense UI displays also include the
full Talisman rank, matching the resistance dice used in combat.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


TALISMAN_SCAN = 0x00055E70  # Stock scan entry after Rockskin handling
SUCCESS_TEST = 0x00000DBA  # Shared resistance success-test routine


class Patch(PatchSpec):
    id = "protection-talisman-resistance-dice"
    description = (
        "Protection Talismans now apply their rank as defensive resistance dice, like Body or "
        "Willpower, instead of applying half their rank as damage reduction. This makes Rank 3 "
        "better than Rank 2, prevents complete bullet immunity with Rank 4 and Heavy Combat "
        "Armor, and allows Protection Talismans to stack with Rockskin."
    )
    category = "Balance Improvements"
    requires = (
        "defense-pip-display-clamp",
        "rockskin-and-talisman-defense-fix",
    )

    def build_patch(self, builder: PatchBuilder) -> None:
        # Add the defender's Protection Talisman rank as resistance dice.
        # Enter the stock scan after its Rockskin branch. The no-match edit
        # below guarantees D7=0, so the rank can be added unconditionally.
        #
        # resistance_dice += find_protection_talisman(defender).rank
        # return success_test(resistance_dice, target_number)
        protection_talisman_resistance_helper_address = builder.add_cave(
            bytes.fromhex(
                f"4EB9{TALISMAN_SCAN:08X}"  # JSR stock Protection Talisman scan
                "DC47"                      # ADD.W D7,D6
                f"4EF8{SUCCESS_TEST:04X}"   # JMP original success_test
            )
        )

        # Add the selected character's Talisman rank to both values prepared by
        # the spell-menu defense renderer, then reproduce its displaced display
        # destination. The scan uses A2 internally, which the UI expects kept.
        spell_menu_talisman_display_helper_address = builder.add_cave(
            bytes.fromhex(
                "2F0A"                      # MOVE.L A2,-(A7)
                "2248"                      # MOVEA.L A0,A1 (selected defender)
                f"4EB9{TALISMAN_SCAN:08X}"  # JSR Protection Talisman scan
                "245F"                      # MOVEA.L (A7)+,A2
                "DC47"                      # ADD.W D7,D6 (physical defense)
                "DA47"                      # ADD.W D7,D5 (mental defense)
                "283C0000C808"              # MOVE.L #$0000C808,D4
                "4E75"                      # RTS
            )
        )

        # The character screen renders physical and mental defense with two
        # calls to the same routine. Add the rank to that call's one value and
        # reproduce the displaced number-tile table pointer.
        character_screen_talisman_display_helper_address = builder.add_cave(
            bytes.fromhex(
                "2F0A"                      # MOVE.L A2,-(A7)
                "2248"                      # MOVEA.L A0,A1 (selected defender)
                f"4EB9{TALISMAN_SCAN:08X}"  # JSR Protection Talisman scan
                "245F"                      # MOVEA.L (A7)+,A2
                "DC47"                      # ADD.W D7,D6 (displayed defense)
                "43F9000CF610"              # LEA ($0CF610).L,A1
                "4E75"                      # RTS
            )
        )

        # Remove the old post-damage flat reduction.
        builder.replace(
            offset=0x055E84,
            source_genesis_sum=39495,
            source_crc32_influence=0x277FCD56,
            payload=bytes.fromhex(
                "4E71"  # SUB.W D7,D5 -> NOP
            ),
        )

        # Return after ordinary post-damage handling instead of rescanning.
        builder.replace(
            offset=0x055E68,
            source_genesis_sum=68288,
            source_crc32_influence=0x4D9A9B09,
            payload=bytes.fromhex(
                "6702"  # BEQ.S test_damage
                "5545"  # SUBQ.W #2,D5 (Rockskin reduction)
                "4A45"  # test_damage: TST.W D5
                "4E75"  # RTS
            ),
        )

        # Use the full Talisman rank rather than halving it.
        builder.replace(
            offset=0x055E82,
            source_genesis_sum=57935,
            source_crc32_influence=0x5F15B850,
            payload=bytes.fromhex(
                "4E71"  # LSR.W #1,D7 -> NOP
            ),
        )

        # Return zero rank when the defender has no Protection Talisman.
        builder.replace(
            offset=0x055E8E,
            source_genesis_sum=19013,
            source_crc32_influence=0xFA855008,
            payload=bytes.fromhex(
                "4247"  # TST.W D5 -> CLR.W D7
            ),
        )

        # Add Talisman dice to firearm, grenade, and direct-spell resistance.
        builder.replace(
            offset=0x0559C8,
            source_genesis_sum=23667,
            source_crc32_influence=0x82BDE082,
            payload=bytes.fromhex(
                "4EB9"  # JSR absolute-long
                f"{protection_talisman_resistance_helper_address}"
            ),
        )

        # Add the same Talisman dice to melee resistance.
        builder.replace(
            offset=0x055D92,
            source_genesis_sum=23667,
            source_crc32_influence=0xA5661078,
            payload=bytes.fromhex(
                "4EB9"  # JSR absolute-long
                f"{protection_talisman_resistance_helper_address}"
            ),
        )

        # Add Talisman rank to the spell menu's physical and mental defense
        # values. This hook follows, and does not overlap, the Dermal hook.
        builder.replace(
            offset=0x0105A6,
            source_genesis_sum=61508,
            source_crc32_influence=0x8102230E,
            payload=bytes.fromhex(
                "4EB9"  # MOVE.L #$0000C808,D4 -> JSR helper
                f"{spell_menu_talisman_display_helper_address}"
            ),
        )

        # Add Talisman rank to each value rendered on the character
        # spell-defense screen. Its routine calls this site once per value.
        builder.replace(
            offset=0x0106FC,
            source_genesis_sum=80405,
            source_crc32_influence=0x8689A7DA,
            payload=bytes.fromhex(
                "4EB9"  # LEA ($0CF610).L,A1 -> JSR helper
                f"{character_screen_talisman_display_helper_address}"
            ),
        )

        # Show the same Talisman dice in the physical Defense value.
        builder.replace(
            offset=0x012E42,
            source_genesis_sum=44320,
            source_crc32_influence=0xD3C6AE6E,
            payload=bytes.fromhex(
                "4EB9"  # JSR old damage-reduction helper -> JSR display helper
                f"{character_screen_talisman_display_helper_address}"
            ),
        )


PATCH = Patch()
