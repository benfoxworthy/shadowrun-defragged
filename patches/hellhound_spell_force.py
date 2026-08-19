"""Reduce Hell Hound fire breath Force from 6 to 5

Hell Hound fire breath uses a special hard-coded attack rather than an ordinary
spell record. It rolls the victim's Body plus shared group spell defense
against Force 6. With Shadowrun's exploding d6 rules, each resistance die
succeeds only one time in six at Force 6; at Force 5 it succeeds two times in
six. Six resistance dice therefore rise from one expected success to two,
roughly one additional box of damage prevented per breath.

Before:
Hell Hounds use a hard-coded enemy direct-attack setup at `0x055B16`, not a
spell-table record. Their actor template at `$1D6816` has mode `$7F`,
spell action 0, Magic 0, and Sorcery 0. The setup loads Force 6 into `D6` for
the attack test, then stores Force 6 in actor `+$9D`; however, the Hell Hound's
direct-attack code never reads that value, instead hardcoding another Force 6
at `0x055B6A`.

    spell_force = 6
    target_number = 4 + modifiers()              # -1 for cybereyes = TN 3
    attack_successes = success_test(spell_force, tn=target_number)
    resistance_successes = success_test(
        Body + sharedPartyMagicalDefense, tn=6   # a separate hardcoded 6
    )
    damage = base_damage + attack_successes - resistance_successes

Patch: Change both the attack pool and the resistance target in the Hell
Hound's attack routine from 6 to 5. These are Hell-Hound-only constants; player
spells, normal enemy mages, and Thon use different paths.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "hellhound-spell-force"
    description = (
        "Reduced Hell Hound's fire breath attack from Force 6 to Force 5. "
        "This makes high Body and shared group spell defense more effective "
        "at reducing damage."
    )
    category = "Balance Improvements"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Lower the hard-coded Hell Hound attack pool from six dice to five.
        builder.replace(
            offset=0x055B18,
            source_genesis_sum=6,
            source_crc32_influence=0xB76563C8,
            payload=bytes.fromhex(
                "0005"  # MOVE.B #6,D6 -> MOVE.B #5,D6
            ),
        )

        # Lower the hardcoded Hell Hound resistance target from Force 6 to 5.
        builder.replace(
            offset=0x055B6A,
            source_genesis_sum=6,
            source_crc32_influence=0x09C09DD2,
            payload=bytes.fromhex(
                "0005"  # MOVE.B #6,D4 -> MOVE.B #5,D4
            ),
        )


PATCH = Patch()
