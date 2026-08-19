"""Let Dermal Plating improvements to Body work against physical magical attacks.

Guns, grenades, and melee all resist damage with Body plus Dermal Plating rank.
Physical spells and the Hell Hound's hardcoded fire breath also resist with
Body, but omitted the cyberware bonus. We can't know if this was intentional,
but since the bonus appears as a modified Body score on the character sheet,
it's more intuitive for it to apply everywhere that Body is used. This gives
better options to protect against Physical spells, which are otherwise quite
hard to mitigate.

Before:

    // Spell Resistance
    resistanceDice = sharedPartySpellDefense();
    if (spell.resistanceType == PHYSICAL)
        resistanceDice += defender.rawBody;
    else
        resistanceDice += defender.willpower;

    // Hell Hound Resistance
    resistanceDice = sharedPartySpellDefense();
    resistanceDice += defender.rawBody;

Patch: Ensure Dermal Plating rank is included in both the physical-spell
resistance branch, the bespoke Hell Hound attack code, and the physical values
shown by both spell-defense UI displays. Nothing changes for mental magic or
other damage types.

    // Spell Resistance
    resistanceDice = sharedPartySpellDefense();
    if (spell.resistanceType == PHYSICAL)
        resistanceDice += bodyPlusDermalPlatingHelper();
    else
        resistanceDice += defender.willpower;

    // Hell Hound Resistance
    resistanceDice = sharedPartySpellDefense();

    // Jump to existing Firearms resistance calculation which already
    // calculates Body + Dermal Plating
    goto firearmsResistanceCalculation

The implementation differs between the two paths due to differences in their
surrounding control flow: Spell resistance cannot simply jump to the existing
Firearms resistance code because that would either skip instructions to set up
its Spell Force and damage mode, or if branched after those instructions,
incorrectly apply Body to Willpower-based spells. Meanwhile, Hell Hounds cannot
easily use the new helper because there is no easy way to create enough extra
bytes for a jump instruction. However, the result of both implementations are
the same.

"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "dermal-plating-spell-resistance"
    description = (
        "Body attribute increases from Dermal Plating now apply to physical spell damage "
        "and Hell Hound fire-breath resistance, not just guns, grenades, and melee attacks."
    )
    category = "Gameplay Bug Fixes"
    requires = ("defense-pip-display-clamp",)

    def build_patch(self, builder: PatchBuilder) -> None:
        # Add the defender's Body and Dermal Plating rank to resistance dice.
        # The rank decoder is copied from the stock firearm resistance path:
        # mutually exclusive cyberware bits 9, 10, and 11 mean ranks 1, 2, and 3.
        #
        # resistance += defender.body
        # resistance += defender.dermal_plating_level  // 0 when not installed
        body_plus_dermal_plating_helper_address = builder.add_cave(
            bytes.fromhex(
                "DC290077"  # ADD.B $77(A1),D6 (original physical Body)
                "48E7C100"  # MOVEM.L D0-D1/D7,-(A7)
                "30290090"  # MOVE.W $90(A1),D0 (cyberware flags)
                "7E02"      # MOVEQ #2,D7 (three Dermal bits)
                "7209"      # MOVEQ #9,D1 (first Dermal bit/rank)
                "0300"      # test_level: BTST.L D1,D0
                "6706"      # BEQ.S next_level
                "5141"      # SUBQ.W #8,D1 (bit 9 -> rank 1)
                "DC41"      # ADD.W D1,D6
                "6006"      # BRA.S done
                "5241"      # next_level: ADDQ.W #1,D1
                "51CFFFF2"  # DBRA D7,test_level
                "4CDF0083"  # done: MOVEM.L (A7)+,D0-D1/D7
                "4E75"      # RTS
            )
        )

        # The spell-menu defense renderer keeps the selected character in A0,
        # while the combat helper expects the defender in A1. Preserve the
        # original copy of shared defense into the mental-defense value, adapt
        # the pointer, and tail-call the common Body-plus-Dermal helper.
        spell_menu_body_plus_dermal_plating_helper_address = builder.add_cave(
            bytes.fromhex(
                "2A06"  # MOVE.L D6,D5 (mental defense starts with shared defense)
                "2248"  # MOVEA.L A0,A1 (selected character becomes defender)
                "4EF9"  # JMP absolute-long (tail-call common helper)
                f"{body_plus_dermal_plating_helper_address}"
            )
        )

        # The character spell-defense screen also keeps the selected character
        # in A0. Add Body plus Dermal Plating, then reproduce the displaced
        # physical-defense display destination before returning.
        character_screen_body_plus_dermal_plating_helper_address = builder.add_cave(
            bytes.fromhex(
                "2248"  # MOVEA.L A0,A1 (selected character becomes defender)
                "4EB9"  # JSR absolute-long
                f"{body_plus_dermal_plating_helper_address}"
                "283C0000C51E"  # MOVE.L #$0000C51E,D4 (physical display field)
                "4E75"  # RTS
            )
        )

        # Replace the physical-spell Body add with the augmented resistance
        # calculation, then skip the mental-spell resistance path.
        builder.replace(
            offset=0x055C10,
            source_genesis_sum=81062,
            source_crc32_influence=0x7331603F,
            payload=bytes.fromhex(
                "4EB9"  # JSR absolute-long
                f"{body_plus_dermal_plating_helper_address}"
                "6004"  # BRA.S $055C1C
            ),
        )

        # The Hell Hound has already accumulated shared party spell defense in
        # D6. Suppress its direct Body add so the existing physical-resistance
        # decoder below can add Body and Dermal Plating exactly once.
        builder.replace(
            offset=0x055B64,
            source_genesis_sum=56480,
            source_crc32_influence=0xD787F93C,
            payload=bytes.fromhex(
                "4E714E71"  # ADD.B $77(A1),D6 -> NOP; NOP
            ),
        )

        # Retarget the Hell Hound's final branch through the stock firearm
        # Body and Dermal Plating decoder at $055996. This code already adds
        # Body plus Dermal Plating, then reaches the same shared resistance
        # roll at $0559BC as before.
        builder.replace(
            offset=0x055B76,
            source_genesis_sum=65094,
            source_crc32_influence=0xF8AAE0AA,
            payload=bytes.fromhex(
                "FE20"  # BRA.W $0559BC -> BRA.W $055996
            ),
        )

        # Show Dermal Plating in the spell menu's physical-defense value. The
        # adjacent Willpower add at $0105A2 remains stock for mental defense.
        builder.replace(
            offset=0x01059C,
            source_genesis_sum=67237,
            source_crc32_influence=0x43B34B2F,
            payload=bytes.fromhex(
                "4EB9"  # MOVE.L D6,D5; ADD.B $77(A0),D6 -> JSR helper
                f"{spell_menu_body_plus_dermal_plating_helper_address}"
            ),
        )

        # Show the same augmented Body value on the character spell-defense
        # screen, then skip over the untouched alternate Willpower branch.
        builder.replace(
            offset=0x0106E4,
            source_genesis_sum=141829,
            source_crc32_influence=0x8F0AF94A,
            payload=bytes.fromhex(
                "4EB9"  # JSR absolute-long
                f"{character_screen_body_plus_dermal_plating_helper_address}"
                "4E714E714E71"  # NOP padding over displaced physical setup
                "600A"  # BRA.S $0106FC (skip alternate Willpower branch)
            ),
        )


PATCH = Patch()
