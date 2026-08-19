"""Use the explicit unarmed action sentinel when a caster loses an action.

The no-weapon fallback at ``0x013478`` accidentally loads one byte from ROM
address ``$007F`` into the actor action field. On the canonical ROM that byte
is ``$20``, which is interpreted by the HUD marker renderer as an ordinary
action index and can corrupt party member health bar graphics. The intended
unarmed sentinel is ``$7F``, matching the other action-reset paths.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "health-bar-graphics-corruption-fix"
    description = (
        "Fixed party member health bar graphics corruption when switching characters "
        "from the pause menu after mental damage forces an unarmed fallback."
    )
    category = "UI/Display Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # MOVE.B ($007F).W,$56(A0) -> MOVE.B #$7F,$56(A0).
        builder.replace(
            offset=0x013478,
            source_genesis_sum=4685,
            source_crc32_influence=0x771F44B5,
            payload=bytes.fromhex("117C007F0056"),
        )


PATCH = Patch()
