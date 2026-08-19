"""Treat the Allegiance shotgun as illegal during Lone Star enforcement.

The Lone Star inventory search and confiscation scans list the illegal weapon
IDs ``$08``, ``$09``, ``$0A``, ``$0C``, and ``$0D``. The Allegiance shotgun is
the omitted intervening item ID ``$0B``, despite its in-game description
identifying it as illegal.

Before:

    if (item == 0x08 ||     // AK97
        item == 0x09 ||     // HK227S
        item == 0x0A ||     // Mach 22
        item == 0x0C ||     // Roomsweeper
        item == 0x0D ||     // Frag Grenade
        item == 0x14 ||     // Maglock Passkey
        item == 0x31 ||     // Light Combat Armor
        item == 0x32) {     // Heavy Combat Armor
        return illegal_item_found;
    }

Patch: In both scans, the first three checks become a contiguous range that
includes Allegiance:

    if (item >= 0x08 && item <= 0x0B)
        return illegal_item_found;

    if (item == 0x0C || item == 0x0D || item == 0x14 ||
        item == 0x31 || item == 0x32) {
        return illegal_item_found;
    }

The original ``item == 0x0A`` comparison remains in the instruction stream but
is unreachable for the new range and harmless for values above ``$0B``. This
preserves every existing item rule with twelve fixed-ROM byte changes and no
code-cave allocation.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "allegiance-shotgun-illegal"
    description = (
        "Fixed Lone Star searches and confiscations not treating the Allegiance shotgun "
        "as an illegal weapon."
    )
    category = "Gameplay Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # if item < $08: continue at the unchanged $0C comparison
        # This replaces BEQ.W illegal with BCS.S + NOP, retaining the same
        # four-byte instruction footprint before the next comparison.
        builder.replace(
            offset=0x0234E6,
            source_genesis_sum=26458,
            source_crc32_influence=0x58CA5199,
            payload=bytes.fromhex("65164E71"),  # BCS.S $0234FE; NOP
        )

        # if item <= $0B: illegal. This includes Allegiance ($0B) as well as
        # the existing $08, $09, and $0A illegal weapon IDs.
        builder.replace(
            offset=0x0234ED,
            source_genesis_sum=9,
            source_crc32_influence=0x020911B9,
            payload=bytes.fromhex("0B"),  # CMPI.B #$09 -> #$0B
        )
        builder.replace(
            offset=0x0234F0,
            source_genesis_sum=26368,
            source_crc32_influence=0x13F60388,
            payload=bytes.fromhex("63"),  # BEQ.W illegal -> BLS.W illegal
        )

        # Apply the same range conversion to the later confiscation scan.
        builder.replace(
            offset=0x0235BE,
            source_genesis_sum=26440,
            source_crc32_influence=0xC7943A76,
            payload=bytes.fromhex("65164E71"),  # BCS.S $0235D6; NOP
        )
        builder.replace(
            offset=0x0235C5,
            source_genesis_sum=9,
            source_crc32_influence=0xFA5BEE45,
            payload=bytes.fromhex("0B"),  # CMPI.B #$09 -> #$0B
        )
        builder.replace(
            offset=0x0235C8,
            source_genesis_sum=26368,
            source_crc32_influence=0x882E9A46,
            payload=bytes.fromhex("63"),  # BEQ.W confiscate -> BLS.W confiscate
        )


PATCH = Patch()
