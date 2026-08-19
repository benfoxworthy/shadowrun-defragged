"""Unscramble firearm attachments

Players had long noticed two apparently unrelated oddities: shotguns could
receive Smartlink accuracy without a Smartgun System, while the supposedly
excellent HK227-S behaved as if its Gas Vents and Laser Sight did nothing.
Both come from one indexing typo. Attachments are stored by inventory slot,
but the accuracy routine indexed the table by the weapon's ID instead.

Before:

    flags = attachment_flags[weapon_id - 1]

Pistols and the AK-97 (IDs 1-8) only worked when the gun happened to occupy
the numerically matching slot. Higher IDs read beyond the attachment array:
the HK227-S read the armor ID, Mach 22 read Body, Allegiance read Quickness,
and Roomsweeper read Strength. Odd attribute values could masquerade as a
Smartgun bit, while the HK's armor byte could never contain the high Gas Vent
bits. It paid the full +3 burst penalty without the upgrades meant to offset
it—up to four target-number points less accurate than a pistol or shotgun.

Patch:

    flags = attachment_flags[equipped_gun_slot]

Retain that slot for all four attachment tests and read
the weapon ID separately only to decide whether the gun is an SMG. Silencers
and Sound Suppressors already used the correct slot in a different routine and
remain untouched. No inventory search is needed, which also preserves distinct
attachments on two copies of the same weapon.

Note: This fix also makes three enemies stronger (none are made weaker)
  Ito / Strike Team (AK-97): Gas Vent II begins working
  Strike Team (Max-Power): Smartgun + Smartlink begins working
  Elven Guard: Smartgun + Smartlink begins working  (This enemy does not appear
   to actually spawn in game, but including for completeness)

Secondary bug fix:

It's possible for an SMG to have both Gas Vent II and III bits set after an
upgrade. The original code checks II first, making the weapon use the weaker
vent. This patch swaps the checks to consider Gas Vent III first. It branches
back to the original Gas Vent II/III subtraction instructions. The separate
SMG balance patch performs its own slot lookup and priority check.

Before:

    if (weapon.isSMG) {
        tn += 3;
        if (flags & GAS_VENT_II) tn -= 2;
        else if (flags & GAS_VENT_III) tn -= 3;
    }

Patch:

    if (weapon.isSMG) {
        tn += 3;
        if (flags & GAS_VENT_III) tn -= 3;
        else if (flags & GAS_VENT_II) tn -= 2;
    }

See ``firearm_attachment_slot_fix_research.md`` for the complete alias table,
the firearm target-number pseudocode, caller audit, enemy-loadout changes, and
regression cases.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "firearm-attachment-slot-fix"
    description = (
        "Fixed weapon attachments: Combat calculations incorrectly indexed weapon attachment "
        "bits using the weapon's ID instead of its slot index, causing calculations for "
        "Smartgun, Laser Sight, and Gas Vents attachments to be scrambled. This change reduces "
        "the effectiveness of Shotguns (they could incorrectly benefit from a Smartlink in many "
        "cases) and improves SMGs (they could almost never benefit from Gas Vents)."
    )
    category = "Gameplay Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Load the attachment slot index instead of the weapon ID.
        builder.replace(
            offset=0x0556C8,
            source_genesis_sum=4223,
            source_crc32_influence=0x0AE3DFEE,
            payload=bytes.fromhex(
                "10280056"  # MOVE.B $57(A0),D0 -> MOVE.B $56(A0),D0
            ),
        )

        # Read the weapon ID directly while retaining the slot index in D0.
        # Stop before the unchanged recoil instruction at $0556DC so the
        # optional gas-vent-balance patch can independently replace it.
        builder.replace(
            offset=0x0556CC,
            source_genesis_sum=60767,
            source_crc32_influence=0x9D41337D,
            payload=bytes.fromhex(
                "0C2800080057"  # CMPI.B #8,$57(A0)
                "6B28"          # BMI.S original below-SMG branch
                "0C28000B0057"  # CMPI.B #11,$57(A0)
                "6A20"          # BPL.S original above-SMG branch
            ),
        )

        # Remove only the weapon-ID decrement while leaving the adjacent stock
        # recoil instruction outside this patch's edit ownership.
        builder.replace(
            offset=0x0556DE,
            source_genesis_sum=21312,
            source_crc32_influence=0x3AD4A5C3,
            payload=bytes.fromhex("4E71"),  # SUBQ.W #1,D0 -> NOP
        )

        # Remove the redundant weapon-ID reload that overwrote the slot index.
        builder.replace(
            offset=0x0556FC,
            source_genesis_sum=25535,
            source_crc32_influence=0xB7A33919,
            payload=bytes.fromhex(
                "4E71"  # NOP
                "4E71"  # NOP
                "4E71"  # NOP
            ),
        )

        # Prefer Gas Vent III when an existing save has both mutually
        # exclusive Gas Vent bits set. D0 is the equipped inventory slot
        # after the edits above. The helper tail-jumps to the stock
        # subtraction sites, allowing gas-vent-balance to NOP the stock
        # pre-clamp arithmetic without overlapping this patch.
        gas_vent_selector = builder.add_cave(
            bytes.fromhex(
                "08300005006E"  # BTST #5, ($6E,A0,D0.W): Gas Vent III
                "6706"          # BEQ.S check Gas Vent II
                "4EF9000556FA"  # JMP Gas Vent III subtraction
                "08300004006E"  # BTST #4, ($6E,A0,D0.W): Gas Vent II
                "6706"          # BEQ.S no Gas Vent
                "4EF9000556EA"  # JMP Gas Vent II subtraction
                "4EF9000556FC"  # JMP subsequent attachment tests
            )
        )
        builder.replace(
            offset=0x0556E0,
            source_genesis_sum=2210,
            source_crc32_influence=0xD78018A5,
            payload=bytes.fromhex(f"4EF9{gas_vent_selector:08X}"),
        )


PATCH = Patch()
