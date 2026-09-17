"""Restore the original attack damage of Renraku Strike Team enemies after
weapon attachment fixes.

Fixing the firearm attachment bug (``firearm-attachment-slot-fix``)
substantially increases the damage of both Renraku Strike Team enemy variants
(including Ito, who shares the AK-97 enemy template): The AK-97 variant was
equipped with a Gas Vent II, and the Max-Power pistol variant had a Smartgun
System, neither of which functioned in the original game.

Fixing the bug makes the Strike Teams extremely lethal: Against a typical
mid-game character wearing an Armor Jacket, compared to the base game, the
pistol variant would deal ~3x damage (~1 damage per shot to ~3 damage per shot)
and the SMG variant would deal ~6x damage (~0.3 → 2 per burst) on average.
(These numbers also include the ``gas-vent-balance`` patch; in Defragged Core,
which doesn't include that patch, the SMG damage would be even higher.)

This patch removes those attachments entirely from the enemy configuration,
which restores their attack target numbers to exactly what they were in the
base game.

Before ``firearm-attachment-slot-fix``:

    Max-Power: Firearms 4; Smartgun (broken)
    AK-97:     Firearms 6; Gas Vent II (broken)

After the attachment fix, without this patch:

    Max-Power: Firearms 4; Smartgun
    AK-97:     Firearms 6; Gas Vent II

Patch:

    Max-Power: Firearms 4; no Smartgun
    AK-97:     Firearms 6; no Gas Vent II

These changes apply to all scripted and random encounters that spawn either
Strike Team enemy variant, including the ambush at Boris' Greenhouse and the
Mako and Ito fights. (Interestingly, the Feathered Serpent Cave encounter uses
an Eye-Fiver template with light pistols, not the Strike Team templates.)
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "renraku-strike-team-damage-fix"
    description = (
        "Restore the original attack damage of Renraku Strike Team enemies "
        "after 'firearm-attachment-slot-fix'."
    )
    category = "Balance Improvements"
    requires = ("firearm-attachment-slot-fix",)

    def build_patch(self, builder: PatchBuilder) -> None:
        # Clear Gas Vent II (bit 4) from the AK-97 template's equipped-weapon
        # attachment byte. Preserve its unrelated attachment bits.
        builder.replace(
            offset=0x1D6AD0,
            source_genesis_sum=5376,
            source_crc32_influence=0x12A79FF8,
            payload=bytes.fromhex("05"),
        )

        # Remove the Smartgun System bit from the Max-Power template's equipped
        # weapon attachment byte. Its Smartlink cyberware remains intact.
        builder.replace(
            offset=0x1D6B1A,
            source_genesis_sum=256,
            source_crc32_influence=0x335B8F9C,
            payload=bytes.fromhex("00"),
        )


PATCH = Patch()
