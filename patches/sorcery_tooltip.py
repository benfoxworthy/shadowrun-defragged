"""Update the Sorcery tooltip to reveal the game's obscure "shared magic-defense" stat.

Shadowrun never tells the player that the party has a shared pool of magical
resistance dice. Every active Mage or Shaman contributes part of their Sorcery
to this pool, even when somebody else is attacked. The total is added to the
Body or Willpower dice of whichever party member is resisting hostile magic.

A high-Sorcery caster is therefore protecting the entire team, not merely
improving their own spells. For example, a Sorcery-12 caster contributes three
dice. Against a physical spell, that is equivalent to every party member
having three additional Body dice; against a mana spell, it is equivalent to
three additional Willpower dice. The bonus also joins Willpower when resisting
the recurring penalties from Stink and Confusion.

Before: The character screen says only:

    "Sorcery determines success with spell casting."

The hidden calculation is approximately:

    shared_magic_defense = 0
    for member in active_party:
        if member.is_mage_or_shaman:
            shared_magic_defense += floor((effective_sorcery(member) + 1) / 4)

    if spell.resists_with_body:
        resistance_dice = defender.Body
    else:
        resistance_dice = defender.Willpower
    resistance_dice += shared_magic_defense

The contribution uses each caster's full effective Sorcery rather than the
share assigned to offense by the Stance slider. It applies only when a party
member resists magic; it does not raise Body or Willpower for ordinary attacks.

Patch: Redirect Sorcery's description pointer to a new three-line string:
``Sorcery determines success with spell casting and improves group spell
defense.`` The panel cannot teach the full formula, but naming the hidden
effect makes an important party-building mechanic discoverable. The stock
renderer and panel already support three lines.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


ORIGINAL_TOOLTIP = 0x000C1E56  # Start of the stock Sorcery tooltip text


class Patch(PatchSpec):
    id = "sorcery-tooltip"
    description = (
        "Updated the Sorcery tooltip: \"Sorcery determines success with spell casting and "
        "improves group spell defense.\""
    )
    category = "UI/Display Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Store the new three-line tooltip in unused ROM space.
        sorcery_tooltip_text_address = builder.add_cave(
            (
                "Sorcery determines success with".encode("ascii")
                + b"\x80"  # Encoded-text line control
                + "spell casting and improves group".encode("ascii")
                + b"\x80"  # Encoded-text line control
                + "spell defense.".encode("ascii")
                + b"\xFF"  # Encoded-text terminator
            )
        )

        # Replace Sorcery's description-table pointer with the new tooltip.
        builder.replace(
            offset=0x0C1B90,
            source_genesis_sum=7778,
            source_crc32_influence=0x19E808CC,
            payload=bytes.fromhex(
                f"{sorcery_tooltip_text_address}"  # DC.L <sorcery_tooltip_text>
            ),
        )


PATCH = Patch()
