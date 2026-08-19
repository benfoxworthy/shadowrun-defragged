"""Reduce Thon's Flame Dart Force from 6 to 5

Like Hell Hound fire breath, Thon's Force 6 makes each Body resistance die
succeed only one time in six. Lowering Force to 5 doubles that to two times in
six: six resistance dice average two successes instead of one, or roughly one
less box of Flame Dart damage per 6 Body.

Before: Thon's special AI selects ordinary Flame Dart, but the final-room
initializer overrides its Force:

    if final_battle_state == ACTIVE:
        thon.current_spell_force = 6

He bypasses the generic enemy spell-profile selector.

Thon's actor template at `0x1EDB00` selects spell mode `$FF`, normal spell
action 1 (Flame Dart), 50-percent pool allocation, Magic 6, and Sorcery 8, but
initializes actor `+$9D` to zero. After the final-room actors are spawned, map
initialization calls `$004388`. When encounter state `$FFE186` is 2, that
routine explicitly writes Force 6 to Thon's fixed actor slot:

```asm
cmpi.b  #$02,($FFE186).l
bne.w   ...
move.b  #$06,($FF049D).l
```

Save states taken during the room-entry dialogue and first cast confirm
`$FFE186=2`, animation set `$000F`, action 1, and `+$9D=6`. Animation set
`$000F` branches to Thon's timer-driven AI at `$013A4C` before the generic
enemy spell-profile selector. That AI calls the ordinary targeted-spell
constructor at `$01033E`, which reads `+$9D` both for casting dice and for
later resistance.

Patch: Change this Thon-specific initializer to Force 5.

Changing the immediate at `0x00439A` initializes only Thon's Flame Dart at
Force 5. It does not affect Hell Hounds, ordinary enemy spellcasters, or
player spells.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "thon-flame-dart-force"
    description = (
        "Reduced Thon's Flame Dart from Force 6 to Force 5. This makes high Body and shared "
        "group spell defense slightly more effective at reducing damage."
    )
    category = "Balance Improvements"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Initialize Thon's Flame Dart at Force 5 instead of Force 6.
        builder.replace(
            offset=0x00439A,
            source_genesis_sum=6,
            source_crc32_influence=0xD6787C9C,
            payload=bytes.fromhex(
                "0005"  # MOVE.B #6,($FF049D).L -> MOVE.B #5,($FF049D).L
            ),
        )


PATCH = Patch()
