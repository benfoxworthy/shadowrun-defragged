"""Fix spells restarting a death animation that is already in progress.

This patch fixes two related bugs with the same root cause:
  1. A spell landing while a death animation is in progress can re-start the
     death animation.
  2. Spells sometimes fail to trigger hit reacts or death animations.

The second bug is minor, but the first bug can cause an enemy to get stuck in
a death animation indefinitely if two or more casters continue to land spells
faster than the animation can finish.

The root cause was a mistake in the effect handlers for Flame Bolt/Hellblast,
Flame Dart, and Mana Zap: These handlers look as if they were supposed to save
the target's previous health before damage resolution, but forgot. Later in the
routine, it accidentally compared health to the spell effect slot index instead
of the intended previous-health value. (Mana Blast follows the same pattern but
implements it correctly, which is evidence of the intended implementation.)

Before:
The Flame Dart, Flame Bolt/Hellblast, and Mana Zap effect handlers all compare
health to D0, which is the spell effect slot index (from an earlier step in the
routine). Previous health was never stored.

    release_effect_slot(effect->slot);  // D0 = `effect->slot`

    save_all_registers();               // all registers saved
    resolve_damage(effect, target);     // may incidentally use D0 as scratch
    restore_all_registers();            // restores `effect->slot` into D0

    if (target->physical_health == effect->slot)  // SHOULD be `prev_health`
        return;

    if (target->physical_health == 0)
        start_death_or_special_death(target);
    else
        start_normal_hit_reaction(target);

If the target's health coincidentally matched the effect slot, the code would
skip any hit react or death animation. Alternatively if they DIDN'T match, this
code could trigger the animation even if health had not changed.

Patch:
Add the missing pre-damage health snapshot to the effect handlers for Flame
Dart, Flame Bolt/Hellblast, and Mana Zap so that they correctly compare the
target's new health with their previous health. Mana Blast/Mana Storm were
already implemented correctly and did not need any change.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


MANA_ZAP_SNAPSHOT = 0x0050C0
FLAME_BOLT_SNAPSHOT = 0x00518E
FLAME_DART_SNAPSHOT = 0x005254


class Patch(PatchSpec):
    id = "spell-repeat-death-anim-fix"
    description = (
        "Fix spells restarting a death animation that is already in progress, and "
        "sometimes skipping death or hit react animations."
    )
    category = "Gameplay Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Mana Zap
        # Preserve the effect-slot bitmap pointer, then snapshot health before
        # the unchanged full-register save.
        mana_zap_snapshot = builder.add_cave(
            bytes.fromhex(
                "265F"          # MOVEA.L (A7)+,A3: displaced restore
                "1028004C"      # MOVE.B $4C(A0),D0: pre-damage health
                "48E7FFFE"      # MOVEM.L D0-D7/A0-A6,-(A7)
                "4EF9000050C6"  # JMP $0050C6: resume after displaced bytes
            )
        )
        builder.replace(
            offset=MANA_ZAP_SNAPSHOT,
            source_genesis_sum=94020,
            source_crc32_influence=0x2CF6D16D,
            payload=bytes.fromhex(f"4EF9{mana_zap_snapshot:08X}"),
        )

        # Flame Dart: Same fix as Mana Zap
        flame_dart_snapshot = builder.add_cave(
            bytes.fromhex(
                "265F"          # MOVEA.L (A7)+,A3: displaced restore
                "1028004C"      # MOVE.B $4C(A0),D0: pre-damage health
                "48E7FFFE"      # MOVEM.L D0-D7/A0-A6,-(A7)
                "4EF90000525A"  # JMP $00525A: resume after displaced bytes
            )
        )
        builder.replace(
            offset=FLAME_DART_SNAPSHOT,
            source_genesis_sum=94020,
            source_crc32_influence=0x6E8C7A8F,
            payload=bytes.fromhex(f"4EF9{flame_dart_snapshot:08X}"),
        )

        # Flame Bolt/Hellblast shared handler
        # Unlike Mana Zap and Flame Dart, Flame Bolt's cleanup region is also
        # rewritten by spell-effect-slot-leak-fix. This hooks at the first
        # post-cleanup instruction to avoid a patch conflict. A3 is already
        # restored by this point.
        #
        # Snapshot health, replay the comparison that was displaced, and then
        # resume at the original BNE.W.
        flame_bolt_snapshot = builder.add_cave(
            bytes.fromhex(
                "1028004C"      # MOVE.B $4C(A0),D0: pre-damage health
                "0C39000300FFE186"  # CMPI.B #3,$FFE186: displaced comparison
                "4EF900005196"  # JMP $005196: resume at the original BNE.W
            )
        )
        builder.replace(
            offset=FLAME_BOLT_SNAPSHOT,
            source_genesis_sum=61121,
            source_crc32_influence=0xD01F4D5B,
            payload=bytes.fromhex(
                f"4EF9{flame_bolt_snapshot:08X}"  # JMP snapshot helper
                "4E71"  # NOP: fill the displaced eight-byte region
            ),
        )


PATCH = Patch()
