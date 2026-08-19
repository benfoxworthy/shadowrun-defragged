"""Let the Lined Duster conceal illegal items during Lone Star encounters.

The Lined Duster's tooltip claims it can "conceal illegal weapons", but this
isn't implemented at all: Lone Star searches every active party member's
inventory for illegal items without consulting their equipped armor. This patch
makes the Lined Duster fully conceal illegal items check when equipped.

The Shadowrun 2e rules only make a Lined Duster improve the chance of
concealment - they don't guarantee success. But, the Lined Duster is weak
otherwise (armor matters a lot), so making it 100% seems reasonable.

Note that this patch doesn't mean illegal items can't be confiscated if you
are arrested through a different dialog branch - it only affects the 'Hey
Flick' search itself.

Before:
Dialogue action 150 searches each active party member's eight inventory slots
after the initial Lone Star Charisma check fails:

    for (member in activeParty) {
        if (member.active)
            searchIllegalItems(member.inventory);
    }

Patch: Treat an active Lined Duster wearer as concealed for this one search,
skipping only that member's inventory. Other active members still undergo the
unchanged scan.

    for (member in activeParty) {
        if (!member.active || member.equippedArmor == LINED_DUSTER)
            continue;
        searchIllegalItems(member.inventory);
    }
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "lined-duster-concealment-fix"
    description = (
        "Make the Lined Duster conceal illegal items during a Lone Star "
        "encounter, as its description claims."
    )
    category = "Gameplay Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Set the same zero flag that the displaced active-member BTST would
        # set for either an inactive member or a Lined Duster wearer. The
        # original BEQ.W then skips to the next party member in both cases.
        # Active non-Duster wearers return with Z clear and enter the stock
        # item-ID scan unchanged.
        concealment_check_address = builder.add_cave(
            bytes.fromhex(
                "082800000010"  # BTST #0,$10(A0)
                "6706"          # BEQ.S return (inactive; preserve Z)
                "0C2800050076"  # CMPI.B #$05,$76(A0) (Lined Duster)
                "4E75"          # return with the resulting Z flag
            )
        )

        # Replace the stock active-member BTST. The following BEQ.W consumes
        # the helper's condition code and retains its original destination.
        builder.replace(
            offset=0x0234D2,
            source_genesis_sum=2104,
            source_crc32_influence=0xCC961CC8,
            payload=bytes.fromhex(
                "4EB9"  # JSR absolute-long concealment check
                f"{concealment_check_address}"
            ),
        )


PATCH = Patch()
