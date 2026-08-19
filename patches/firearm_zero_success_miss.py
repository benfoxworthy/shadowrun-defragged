"""Make zero-success firearms attacks miss completely.

Stock firearm damage always includes the weapon's base damage even when the
attack roll stored zero successes on the projectile. This means that a firearms
attack effectively can't "miss" unless the target resists the damage with armor
or a resistance roll. While this has minimal effect on game balance during most
normal gameplay, it's inconsistent with melee and spell attacks and with the SR
TTRPG rules. It's also unintuitive that high-damage firearms can be effective
even with 0 Firearms skill.

Patch: Add a gate that runs before the target's resistance roll and all damage
staging. A zero-success projectile now returns from the firearm-impact resolver
immediately, causing neither a resistance roll nor base damage.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


FIREARM_IMPACT_RESOLVER = 0x055948
FIREARM_IMPACT_CONTINUE = 0x05594E


class Patch(PatchSpec):
    id = "firearm-zero-success-miss"
    description = (
        "Made zero-success firearm attacks miss completely. The projectile no longer "
        "deals base weapon damage or triggers a target resistance roll when its attack "
        "roll has no successes."
    )
    category = "Gameplay Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        zero_success_gate = builder.add_cave(
            bytes.fromhex(
                "423900FFF0CC"  # displaced CLR.B $FFF0CC
                "4A28009F"      # TST.B $9F(A0): projectile attack successes
                "6706"          # BEQ.S miss
                f"4EF9{FIREARM_IMPACT_CONTINUE:08X}"  # JMP stock resolver body
                "4E75"          # miss: RTS
            )
        )
        builder.replace(
            offset=FIREARM_IMPACT_RESOLVER,
            source_genesis_sum=78852,
            source_crc32_influence=0xD37472DD,
            payload=bytes.fromhex(f"4EF9{zero_success_gate:08X}"),
        )


PATCH = Patch()
