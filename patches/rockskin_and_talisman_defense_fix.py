"""Fix Protection Talisman and Rockskin actually protecting enemies

This is a simple bug behind a long-standing player suspicion: Rockskin and
Protection Talismans really were “broken,” but their formulas were running. The
shared routine merely confused its attacker and defender pointers. A protected
mage reduced the damage of the spell they cast; a protected victim received no
benefit.

Before:

    if attacker.has_rockskin:
        damage -= 2
    else if attacker.inventory.contains(ProtectionTalisman):
        damage -= floor(talisman.rank / 2)

Patch: Change the two relevant pointer operands from attacker to defender—one
for the Rockskin bit and one for the talisman inventory scan. The stock effects
and all surrounding damage arithmetic remain unchanged.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "rockskin-and-talisman-defense-fix"
    description = (
        "Fixed Protection Talismans and Rockskin incorrectly reducing damage dealt instead of "
        "damage taken."
    )
    category = "Gameplay Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Test Rockskin on the defender rather than the attacker.
        builder.replace(
            offset=0x055E62,
            source_genesis_sum=2088,
            source_crc32_influence=0x7CCA4792,
            payload=bytes.fromhex(
                "0829"  # BTST #5,$11(a0) -> BTST #5,$11(a1)
            ),
        )

        # Scan the defender's inventory for a Protection Talisman.
        builder.replace(
            offset=0x055E70,
            source_genesis_sum=9288,
            source_crc32_influence=0x59E6A522,
            payload=bytes.fromhex(
                "2449"  # MOVEA.L a0,a2 -> MOVEA.L a1,a2
            ),
        )


PATCH = Patch()
