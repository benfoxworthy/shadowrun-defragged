"""Prevent mental damage from killing Thon and causing a stuck game state.

The combat sources relevant to this bug apply Mental damage to NPCs at two
independent sites:

* The shared ranged/spell damage tail reaches its Mental route when `$FFF0CC`
  is nonzero. This covers Sleep spell damage and Concussion grenades. Its
  lethal Mental block starts at `0x055A86`; its Physical route starts at
  `0x055A90`.
* The melee resolver has a separate Mental block at `0x055E54`. Bare-handed
  attacks use it, while Spurs and Hand Razors select the melee Physical route
  at `0x055DEE`. Stock branches directly to the common tail when the result is
  exactly zero and falls through to its clear only when the result is negative.
  The patch changes that boundary at `0x055E58`, then hooks the zero-or-negative
  Mental block at `0x055E5A`.

Stock code clears actor `+$9C` on either lethal Mental path without passing
through the corresponding Physical route. Thon's final encounter needs his
Physical track to reach its defeat state for the ending script to advance.

The other direct Mental-track reductions are not additional lethal damage
paths for Thon. NPC spell drain at `0x055BE8` clamps the caster to one Mental
box, and the Matrix failure write at `0x0185B6` targets the active party member
and also clamps to one. Party combat damage uses the status-panel helper at
`0x0037EC`; the two NPC branches above are selected for Thon instead.

Thon's unit template at `0x1EDB00` has no unique runtime unit-type ID. The
actor initializer does, however, save its coordinate-source pointer at actor
`+$E0`; `$001EDAC8`, the first record in the final-room spawn list, uniquely
identifies Thon.

Patch: Replace both already-lethal Mental blocks with path-specific helpers.
For other actors, each helper replays the displaced Mental-track clear and
stock continuation. For Thon, each helper retains one Mental box and
tail-jumps to that resolver's stock Physical route with the existing staged
damage in `D1`. This includes lethal bare-handed melee damage. Nonlethal Mental
hits, Spurs/Hand Razors, and every ordinary Physical hit retain their original
instructions.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


SPAWN_RECORD = 0x001EDAC8  # Unique Thon coordinate-source record used as runtime ID
SHARED_PHYSICAL_DAMAGE_BRANCH = 0x00055A90
SHARED_COMMON_DEATH_PATH = 0x00055A9E
MELEE_PHYSICAL_DAMAGE_BRANCH = 0x00055DEE
MELEE_COMMON_DAMAGE_TAIL = 0x00055DFC


class Patch(PatchSpec):
    id = "thon-lethal-mental-damage-fix"
    description = (
        "Fixed a stuck state after killing Thon with Mental damage. Mental damage to Thon is "
        "now converted to Physical damage when it would otherwise be fatal."
    )
    category = "Gameplay Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Route Thon's lethal shared-resolver Mental damage through that
        # resolver's physical damage handling. This site is used by Sleep
        # damage and Concussion grenades, but not by bare-handed melee.
        # Actor +$E0 holds the source coordinate-record pointer installed at
        # spawn time; $001EDAC8 uniquely identifies Thon's map spawn.
        #
        # if actor.spawn_record == SPAWN_RECORD:
        #     actor.mental_health = 1
        #     continue_with_physical_damage()
        # else:
        #     continue_with_normal_mental_death()
        thon_lethal_mental_damage_helper_address = builder.add_cave(
            bytes.fromhex(
                f"0CA9{SPAWN_RECORD:08X}00E0"        # CMPI.L #Thon spawn,$E0(A1)
                "660C"                               # BNE.S ordinary_mental_death
                "137C0001009C"                       # MOVE.B #1,$9C(A1)
                f"4EF9{SHARED_PHYSICAL_DAMAGE_BRANCH:08X}"  # JMP physical branch
                "4229009C"                           # ordinary_mental_death: CLR.B $9C(A1)
                f"4EF9{SHARED_COMMON_DEATH_PATH:08X}"  # JMP common death path
            )
        )

        # Replace the lethal Mental branch with Thon-specific physical routing.
        builder.replace(
            offset=0x055A86,
            source_genesis_sum=29736,
            source_crc32_influence=0x8EDB9B3B,
            payload=bytes.fromhex(
                "4EF9"  # JMP absolute-long
                f"{thon_lethal_mental_damage_helper_address}"
                "4E71"  # NOP
                "4E71"  # NOP
            ),
        )

        # Bare-handed melee applies Mental damage in a completely separate
        # block. Stock BPL skips its clear when the result is exactly zero, so
        # make that BGT: positive hits still return directly, while both zero
        # and negative results reach the helper. For Thon, retain one Mental
        # box and reapply D1 through the stock melee Physical path; for every
        # other actor, replay the clear and stock continuation.
        thon_lethal_melee_mental_damage_helper_address = builder.add_cave(
            bytes.fromhex(
                f"0CA9{SPAWN_RECORD:08X}00E0"        # CMPI.L #Thon spawn,$E0(A1)
                "660C"                               # BNE.S ordinary_mental_death
                "137C0001009C"                       # MOVE.B #1,$9C(A1)
                f"4EF9{MELEE_PHYSICAL_DAMAGE_BRANCH:08X}"  # JMP melee Physical route
                "4229009C"                           # ordinary_mental_death: CLR.B $9C(A1)
                f"4EF9{MELEE_COMMON_DAMAGE_TAIL:08X}"  # JMP stock melee continuation
            )
        )

        builder.replace(
            offset=0x055E58,
            source_genesis_sum=27298,
            source_crc32_influence=0xFE8E84B9,
            payload=bytes.fromhex(
                "6EA2"  # BPL.S common tail -> BGT.S common tail
            ),
        )

        builder.replace(
            offset=0x055E5A,
            source_genesis_sum=29874,
            source_crc32_influence=0xEBD3E989,
            payload=bytes.fromhex(
                "4EF9"  # JMP absolute-long
                f"{thon_lethal_melee_mental_damage_helper_address}"
                "4E71"  # NOP
            ),
        )


PATCH = Patch()
