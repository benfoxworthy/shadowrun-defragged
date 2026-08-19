"""Fix spell casts leaking effect slots, eventually preventing all spells
and firearms attacks from firing (making multi-caster parties non-viable),
and fix AoE spells leaking tracking state.

The game has eighteen shared dynamic graphics/effect slots which are used by
spell effects, bullets, and other graphics. They are supposed to be assigned
during a spell cast and then released when the effect is done. However, the
code had multiple bugs where these could leak. Once all slots were used up,
both spells and firearms attacks would fail until a map change. Parties with
multiple spell casters would trigger this bug especially often, making them
essentially non-viable.

Some of these cases could also leak tracking state on the targets of AoE
spells (Hellblast, Mana Storm, Sleep, Confusion, and Stink). This could confuse
the targets of future casts of the same spell. More importantly, for Confusion
and Stink, the leaked state could cause a target to be affected by the debuff
indefinitely (until a later completed cast cleared it, or the actor reset) even
though no visible spell effect was shown.

Before:

The engine limits each unit (target) to tracking a single in-progress spell at
a time. If a new spell is targeted at a unit already playing a spell effect,
it cancels and replaces the previous spell. However, there were multiple cases
where ownership of the effect slot was not tracked correctly, causing leaks:

1. When a targeted spell began hitting a target with an existing effect in
   progress, it would replace the previous effect - leaking it. This was the
   most common way for this bug to surface with multiple casters.

2. AoE spells had specific handlers that would reuse the same effect slot
   across multiple targets, "chaining" the effect. This had the same bug as #1,
   but in different codepaths. (Additionally, some of these handlers would
   release the effect between each target while continuing to use its slot ID,
   corrupting allocation tracking and possibly causing graphical glitches - but
   this is unconfirmed.)

3. When Invisibility or Rockskin was cast, it would always allocate an effect
   that it never used, causing an immediate leak. Thus, casting either spell
   enough times in a row would trigger the bug, even with a single caster.

4. Finally, actor teardown/destruction could cause a leak if a spell effect was
   still in progress when the actor was fully despawned. This seems unlikely
   to happen in practice, but is still included for completeness.

5. Interrupting an AoE could additionally orphan its per-actor candidate
   markers. Stink and Confusion also left their logical status bits set after
   their sole effect controller was replaced, so their gameplay penalty could
   persist without any remaining effect to finish the chain and clear it.

Patch: This patch minimally fixes the known leaks while largely preserving the
original engine behavior: Each actor is still limited to a single in-progress
spell at a time (most recent cast wins), but effect slot tracking is hardened
to prevent leaks and interrupted AoEs no longer leave orphaned logical state.
Each fix is explained in more detail in-line.

Note that this minimal fix means that odd gameplay behaviors can still occur:
for example, damage or healing from a spell can be cancelled if another spell
lands mid-effect. This means that parties with multiple casters may still be
at a disadvantage.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


ALLOCATE_DYNAMIC_EFFECT_SLOT = 0x0001A2CC
RELEASE_DYNAMIC_EFFECT_SLOT = 0x0001A304
SPELL_SETUP_CONTINUE = 0x0001586E
SPELL_SETUP_FAIL = 0x0001592E


class Patch(PatchSpec):
    id = "spell-effect-slot-leak-fix"
    description = (
        "Fix spell casts leaking effect slots, eventually preventing all "
        "spells and firearms attacks from firing (making multi-caster "
        "parties non-viable). Also fixes orphaned Stink/Confusion state."
    )
    category = "Gameplay Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Issue 5, shared logical-state cleanup for AoEs:
        # cleanup_orphaned_aoe_state(D0 = cancelled_action):
        # Remove the candidate/status state of an interrupted AoE, but only
        # after its last active effect controller has disappeared.
        #
        # The candidate set is not stored in a separate object. Each of the ten
        # standard actors instead carries the AoE action in +$DE. Stink and
        # Confusion additionally set +$DF bits 0 and 1. This state is normally
        # cleared at the end of the chain, but replacing the active effect
        # prevents that cleanup from running. This cleanup is hooked into the
        # effect cancellation paths to fix that gap.
        #
        # if (cancelled_action == 0)
        #     return;
        # for (actor = standard_actor[0]; actor <= standard_actor[9]; ++actor) {
        #     if (actor->active &&
        #         actor->attached_action == cancelled_action)
        #         return;  // another controller still owns the logical state
        # }
        # for (actor = standard_actor[0]; actor <= standard_actor[9]; ++actor) {
        #     if (actor->aoe_candidate_action == cancelled_action)
        #         actor->aoe_candidate_action = 0;
        #     if (cancelled_action == Stink)
        #         actor->stink = false;
        #     else if (cancelled_action == Confusion)
        #         actor->confusion = false;
        # }
        # return;
        #
        # D0 is preserved. D1 and A1 are saved because callers still need their
        # allocator/target state. The status timers and shared return pointer
        # are deliberately left alone: they are inert without a +$B2 owner,
        # and a different incoming status AoE may already have initialized
        # them before its first-target collision is discovered.
        cleanup_orphaned_aoe_state = builder.add_cave(
            bytes.fromhex(
                "4A00"  # TST.B D0: was there a cancelled action?
                "6700006C"  # BEQ.W done
                "3F01"  # MOVE.W D1,-(A7): preserve caller's D1
                "2F09"  # MOVE.L A1,-(A7): preserve caller's A1
                "43F900FF0100"  # LEA $FF0100,A1: first standard actor
                "323C0009"  # MOVE.W #9,D1: scan ten standard actors
                "B02900B2"  # owner_scan: CMP.B $B2(A1),D0
                "6600000C"  # BNE.W next_owner
                "082900000010"  # BTST #0,$10(A1): is this owner active?
                "66000048"  # BNE.W restore: another live controller exists
                "D2FC0100"  # next_owner: ADDA.W #$100,A1
                "51C9FFE8"  # DBRA D1,owner_scan
                "43F900FF0100"  # LEA $FF0100,A1: restart at first actor
                "323C0009"  # MOVE.W #9,D1: clean ten actor records
                "B02900DE"  # cleanup_scan: CMP.B $DE(A1),D0
                "66000006"  # BNE.W keep_marker
                "422900DE"  # CLR.B $DE(A1): remove this action's marker
                "0C000006"  # keep_marker: CMPI.B #6,D0: Stink?
                "67000014"  # BEQ.W clear_stink
                "0C00000D"  # CMPI.B #13,D0: Confusion?
                "66000012"  # BNE.W next_cleanup
                "08A9000100DF"  # BCLR #1,$DF(A1): clear Confusion state
                "60000008"  # BRA.W next_cleanup
                "08A9000000DF"  # clear_stink: BCLR #0,$DF(A1)
                "D2FC0100"  # next_cleanup: ADDA.W #$100,A1
                "51C9FFCE"  # DBRA D1,cleanup_scan
                "225F"  # restore: MOVEA.L (A7)+,A1
                "321F"  # MOVE.W (A7)+,D1
                "4E75"  # done: RTS
            )
        )

        # Issues 1, 2, 4, and 5, shared cancellation helper:
        # release_existing_target_effect(A1 = target, D0 = incoming_action):
        # Safely release an attached effect, then clean its distributed AoE
        # state if no active controller remains. A same-action replacement does
        # not clean anything because the incoming effect inherits the shared
        # candidate/status state and will run the normal terminal cleanup.
        #
        # if (target->attached_action != 0) {
        #     old_action = target->attached_action;
        #     release_dynamic_effect_slot(target->attached_slot);
        #     target->attached_action = 0;
        #     if (old_action != incoming_action)
        #         cleanup_orphaned_aoe_state(old_action);
        # }
        # return;
        #
        # D0, D1, and A3 are preserved. A1 is preserved by the cleanup helper.
        release_existing_target_effect = builder.add_cave(
            bytes.fromhex(
                "4A2900B2"  # TST.B $B2(A1): is an effect attached?
                "67000032"  # BEQ.W done
                "3F00"  # MOVE.W D0,-(A7): preserve incoming action
                "3F01"  # MOVE.W D1,-(A7): preserve caller's D1
                "4241"  # CLR.W D1
                "122900B2"  # MOVE.B $B2(A1),D1: capture old action
                "2F0B"  # MOVE.L A3,-(A7): preserve allocator pointer
                "30290032"  # MOVE.W $32(A1),D0: load old slot ID
                f"4EB9{RELEASE_DYNAMIC_EFFECT_SLOT:08X}"  # JSR release_dynamic_effect_slot
                "265F"  # MOVEA.L (A7)+,A3: restore allocator pointer
                "422900B2"  # CLR.B $B2(A1): unpublish old controller
                "B22F0003"  # CMP.B $3(A7),D1: same incoming action?
                "6700000A"  # BEQ.W restore: incoming effect owns cleanup
                "3001"  # MOVE.W D1,D0: pass old action to cleanup
                f"4EB9{cleanup_orphaned_aoe_state:08X}"  # JSR cleanup_orphaned_aoe_state
                "321F"  # restore: MOVE.W (A7)+,D1
                "301F"  # MOVE.W (A7)+,D0
                "4E75"  # done: RTS
            )
        )

        # Issues 1, 3, and 5:
        # setup_effect_slot(A0 = caster, A1 = target):
        # Helper that safely sets up a dynamic effect slot for a spell.
        # Releases the existing used effect slot when replacing an in-progress
        # spell with a newer spell, and releases the unused effect slot
        # allocated by Invisibility / Rockskin.
        # Preserves stock behavior: Rockskin and Invisibility still replace
        # an in-progress spell and fail if allocation fails, but don't leak their
        # effect.
        #
        # if (!target->active)
        #     goto stock_failed_setup;
        # old_action = target->attached_action;
        # release_existing_target_effect(target, caster->spell_action);
        # slot = allocate_dynamic_effect_slot();
        # if (allocation_failed) {
        #     cleanup_orphaned_aoe_state(old_action);
        #     goto stock_failed_setup;
        # }
        #
        # if (caster->spell_action == Invisibility ||
        #     caster->spell_action == Rockskin)
        #     release_dynamic_effect_slot(slot);
        # goto stock_successful_setup;
        #
        # D0 returns the newly allocated slot ID on success. The saved old
        # action matters when old and incoming actions match: cancellation
        # initially preserves their shared logical state, but allocation
        # failure means no new controller exists to finish that state. Immediate
        # buffs keep the numeric slot value for the stock setup tail, but its
        # allocator entry is already released because they need no visual slot.
        setup_effect_slot = builder.add_cave(
            bytes.fromhex(
                "082900000010"  # BTST #0,$10(A1): is the target active?
                "67000050"  # BEQ.W failed_setup_without_saved_action
                "4240"  # CLR.W D0
                "102900B2"  # MOVE.B $B2(A1),D0: remember old action
                "3F00"  # MOVE.W D0,-(A7): save it through allocation
                "4240"  # CLR.W D0
                "10280057"  # MOVE.B $57(A0),D0: incoming spell action
                f"4EB9{release_existing_target_effect:08X}"  # JSR release_existing_target_effect
                f"4EB9{ALLOCATE_DYNAMIC_EFFECT_SLOT:08X}"  # JSR allocate_dynamic_effect_slot
                "6500002A"  # BCS.W failed_setup
                "548F"  # ADDQ.L #2,A7: discard saved old action
                "0C2800040057"  # CMPI.B #4,$57(A0): Invisibility?
                "67000012"  # BEQ.W release_immediate
                "0C28000B0057"  # CMPI.B #11,$57(A0): Rockskin?
                "67000008"  # BEQ.W release_immediate
                f"4EF9{SPELL_SETUP_CONTINUE:08X}"  # JMP stock successful setup
                f"4EB9{RELEASE_DYNAMIC_EFFECT_SLOT:08X}"  # release_immediate: JSR release_dynamic_effect_slot
                f"4EF9{SPELL_SETUP_CONTINUE:08X}"  # JMP stock successful setup
                "301F"  # failed_setup: MOVE.W (A7)+,D0: recover old action
                f"4EB9{cleanup_orphaned_aoe_state:08X}"  # JSR cleanup_orphaned_aoe_state
                f"4EF9{SPELL_SETUP_FAIL:08X}"  # failed_setup_without_saved_action: JMP stock failure
            )
        )

        # Issues 2 and 5, first target: attach a newly constructed spell effect
        # to the actor that common setup ultimately selected, without leaking
        # that actor's existing effect or orphaning its old logical AoE state.
        #
        # Most spells still use the original A1 target that setup_effect_slot
        # already cleaned. Stink and Confusion are different: their shared AoE
        # candidate builder can select another actor and replace A1 before the
        # common publication at $0158E0. This second cleanup point is therefore
        # required for the actor that actually receives the effect.
        #
        # The builder also used to write the new Stink/Confusion action into
        # that actor before its new slot was installed. The $015A36 hook below
        # suppresses that premature write, leaving the old action visible here
        # if an existing effect really exists. This helper releases it and
        # then replays the common action publication that its hook replaces.
        #
        # attach_effect_to_selected_target(A0 = caster, A1 = selected_target):
        #
        # release_existing_target_effect(selected_target,
        #                                caster->spell_action);
        # selected_target->attached_action = caster->spell_action;
        # return;
        #
        # Stock setup then publishes the new slot and remaining effect fields.
        attach_effect_to_selected_target = builder.add_cave(
            bytes.fromhex(
                "3F00"  # MOVE.W D0,-(A7): preserve incoming slot ID
                "4240"  # CLR.W D0
                "10280057"  # MOVE.B $57(A0),D0: incoming spell action
                f"4EB9{release_existing_target_effect:08X}"  # JSR release_existing_target_effect
                "301F"  # MOVE.W (A7)+,D0: restore incoming slot ID
                "1368005700B2"  # MOVE.B $57(A0),$B2(A1): publish cast action
                "4E75"  # RTS
            )
        )

        # Issue 2, slot lifetime: keep one allocation live for the entire
        # Hellblast, Sleep, or Mana Storm chain and release it only after the
        # final target.
        #
        # Stock released the slot whenever one target's animation completed,
        # then its AoE wrapper copied the same now-free numeric ID to the next
        # target. Usually a later leg merely released an already-free ID, but
        # another projectile could claim that ID between legs; the next AoE
        # release would then free somebody else's allocation.
        #
        # The three patched cleanup sites are shared by direct and AoE actions:
        # Mana Blast/Mana Storm, Flame Bolt/Hellblast, and Sleep's own handler.
        # This helper reads the current action to distinguish them. Direct
        # spells still clear and release immediately. A sequential AoE clears
        # the completed actor but scans for another stock-eligible marked
        # target. If one exists, it returns the still-live slot ID so the stock
        # wrapper can hand it off; otherwise it performs the one final release.
        #
        # The scan duplicates the wrapper's eligibility test because the slot
        # must remain allocated before control returns to that wrapper.
        #
        # finish_spell_effect_on_target(A0 = current_target):
        #
        # saved_d1 = D1;
        # saved_a1 = A1;
        # action = current_target->attached_action;
        # if (action == Hellblast || action == Sleep || action == ManaStorm) {
        #     current_target->attached_action = 0;
        #     current_target->aoe_candidate_action = 0;
        #     for (candidate = actor[0]; candidate <= actor[9]; ++candidate) {
        #         if (candidate->aoe_candidate_action == action &&
        #             candidate->active && !candidate->ineligible_bit_6) {
        #             D0 = current_target->attached_slot;
        #             restore(saved_a1, saved_d1);
        #             return;  // wrapper will transfer the retained slot
        #         }
        #     }
        # } else {
        #     current_target->attached_action = 0;
        #     current_target->aoe_candidate_action = 0;
        # }
        # D0 = current_target->attached_slot;
        # release_dynamic_effect_slot(D0);
        # restore(saved_a1, saved_d1);
        # return;
        #
        # Flame Bolt and Mana Blast share these completion sites with
        # Hellblast and Mana Storm, so non-AoE actions take the release path.
        finish_spell_effect_on_target = builder.add_cave(
            bytes.fromhex(
                "3F01"  # MOVE.W D1,-(A7): preserve caller's D1
                "2F09"  # MOVE.L A1,-(A7): preserve caller's A1
                "4280"  # CLR.L D0
                "102800B2"  # MOVE.B $B2(A0),D0: load completing action
                "0C000003"  # CMPI.B #3,D0: Hellblast?
                "67000016"  # BEQ.W sequential
                "0C000005"  # CMPI.B #5,D0: Sleep?
                "6700000E"  # BEQ.W sequential
                "0C00000A"  # CMPI.B #10,D0: Mana Storm?
                "67000006"  # BEQ.W sequential
                "6000003C"  # BRA.W clear_and_release for direct spells
                "422800B2"  # sequential: CLR.B $B2(A0): finish current owner
                "422800DE"  # CLR.B $DE(A0): consume current candidate marker
                "43F900FF0100"  # LEA $FF0100,A1: first standard actor
                "323C0009"  # MOVE.W #9,D1: scan ten standard actors
                "B02900DE"  # scan: CMP.B $DE(A1),D0: same AoE marker?
                "66000016"  # BNE.W next
                "082900000010"  # BTST #0,$10(A1): candidate active?
                "6700000C"  # BEQ.W next
                "082900060010"  # BTST #6,$10(A1): candidate ineligible?
                "67000028"  # BEQ.W retain
                "D2FC0100"  # next: ADDA.W #$100,A1: advance actor record
                "51C9FFDE"  # DBRA D1,scan
                "6000000A"  # BRA.W release: no candidate remains
                "422800B2"  # clear_and_release: CLR.B $B2(A0)
                "422800DE"  # CLR.B $DE(A0)
                "30280032"  # release: MOVE.W $32(A0),D0: load slot ID
                "2F0B"  # MOVE.L A3,-(A7): preserve effect-slot bitmap pointer
                f"4EB9{RELEASE_DYNAMIC_EFFECT_SLOT:08X}"  # JSR release_dynamic_effect_slot
                "265F"  # MOVEA.L (A7)+,A3: restore effect-slot bitmap pointer
                "60000006"  # BRA.W restore
                "30280032"  # retain: MOVE.W $32(A0),D0 for stock wrapper
                "225F"  # restore: MOVEA.L (A7)+,A1
                "321F"  # MOVE.W (A7)+,D1
                "4E75"  # RTS
            )
        )

        # Issues 2 and 5, later targets: transfer a running AoE to the next
        # actor without leaking an effect already attached to that actor or
        # orphaning its old logical AoE state.
        #
        # Each AoE handler marks all potential targets by storing its action ID
        # in actor->aoe_candidate_action ($DE). After the current target's
        # effect finishes, the handler finds the next eligible marked actor and
        # reaches one of the five handoff hooks below. Stock immediately wrote
        # its action into that actor, overwriting any attached spell reference.
        #
        # This helper first releases that existing effect, then publishes the
        # action already stored in the candidate marker. The unchanged stock code
        # after the hook copies the retained slot ID, caster, graphics tile,
        # and animation state from the current target into the new target.
        #
        # chain_aoe_to_next_target(A1 = next_target):
        #
        # release_existing_target_effect(next_target,
        #                                next_target->aoe_candidate_action);
        # next_target->attached_action = next_target->aoe_candidate_action;
        # return;
        #
        chain_aoe_to_next_target = builder.add_cave(
            bytes.fromhex(
                "3F00"  # MOVE.W D0,-(A7): preserve actor-scan counter/state
                "4240"  # CLR.W D0
                "102900DE"  # MOVE.B $DE(A1),D0: incoming AoE action
                f"4EB9{release_existing_target_effect:08X}"  # JSR release_existing_target_effect
                "301F"  # MOVE.W (A7)+,D0: restore caller's D0
                "136900DE00B2"  # MOVE.B $DE(A1),$B2(A1): publish incoming AoE
                "4E75"  # RTS
            )
        )

        # Issues 4 and 5:
        # deallocate_attached_effect(A0 = actor):
        # Deallocates an effect attached to an actor during actor teardown and
        # removes its logical AoE state if this was the last active controller.
        #
        # actor->active = false;  // displaced stock operation
        # release_existing_target_effect(actor, 0);
        # return;  // stock teardown resumes at $01E52A
        deallocate_attached_effect = builder.add_cave(
            bytes.fromhex(
                "08A800000010"  # BCLR #0,$10(A0): displaced stock instruction
                "3F00"  # MOVE.W D0,-(A7): preserve caller's D0
                "2F09"  # MOVE.L A1,-(A7): preserve caller's A1
                "2248"  # MOVEA.L A0,A1: target uses common helper contract
                "4240"  # CLR.W D0: teardown has no incoming action
                f"4EB9{release_existing_target_effect:08X}"  # JSR release_existing_target_effect
                "225F"  # MOVEA.L (A7)+,A1: restore caller's A1
                "301F"  # MOVE.W (A7)+,D0: restore caller's D0
                "4E75"  # RTS
            )
        )

        # Issues 1, 3, and 5:
        # Hook the improved setup_effect_slot when a spell applies to a target,
        # replacing the stock allocator call and failure branch with
        # cancellation, allocation, and failed-replacement cleanup:
        #     slot = allocate_dynamic_effect_slot();
        #     if (allocation_failed)
        #         return;
        # On success setup_effect_slot jumps to $01586E, the exact next stock
        # instruction, so all remaining spell initialization is unchanged.
        builder.replace(
            offset=0x015868,
            source_genesis_sum=51074,
            source_crc32_influence=0xF2AF6CE6,
            payload=bytes.fromhex(
                f"4EF9{setup_effect_slot:08X}"  # JMP setup_effect_slot
            ),
        )

        # Issue 2, first AoE target (part 1): Stink/Confusion's candidate
        # builder used to publish the new action before installing its slot.
        # Suppress that early write so an existing effect remains identifiable
        # until attach_effect_to_selected_target can release it. If there is no
        # existing effect, $B2 remains zero and no stale $32 value is released.
        builder.replace(
            offset=0x015A36,
            source_genesis_sum=4594,
            source_crc32_influence=0x4A0E9AF5,
            payload=bytes.fromhex(
                "4E71"  # NOP: suppress premature action publication
                "4E71"  # NOP: complete displaced four-byte instruction
            ),
        )
        # Issues 2 and 5, first AoE target (part 2): replace the common
        # action-field write with attach_effect_to_selected_target. It releases
        # any effect attached to the actor ultimately selected by the candidate
        # builder, cleans orphaned old logical state, replays the displaced
        # write, then returns to stock slot/tile setup.
        builder.replace(
            offset=0x0158E0,
            source_genesis_sum=5233,
            source_crc32_influence=0x0B3A8881,
            payload=bytes.fromhex(
                f"4EB9{attach_effect_to_selected_target:08X}"  # JSR attach_effect_to_selected_target
            ),
        )

        # Issue 2, chained slot lifetime: replace the stock clear-and-release
        # sequence shared by Mana Blast/Mana Storm, Flame Bolt/Hellblast, and
        # Sleep. finish_spell_effect_on_target retains the allocation only for
        # sequential AoEs with another eligible target; direct spells and final
        # AoE legs still release it. The NOPs fill the rest of each displaced
        # 22-byte cleanup sequence before stock damage/resolution code resumes.
        for offset, source_genesis_sum, source_crc32_influence in (
            (0x005008, 130402, 0x7944A720),
            (0x005178, 130402, 0xF2A92369),
            (0x005348, 130402, 0x902E03BB),
        ):
            builder.replace(
                offset=offset,
                source_genesis_sum=source_genesis_sum,
                source_crc32_influence=source_crc32_influence,
                payload=bytes.fromhex(
                    f"4EB9{finish_spell_effect_on_target:08X}"  # JSR finish_spell_effect_on_target
                    "4E714E714E714E714E714E714E714E71"  # NOP x8: fill displaced 22-byte cleanup
                ),
            )

        # Issues 2 and 5, later AoE targets: each stock handoff began by
        # overwriting next_target->attached_action with the incoming action.
        # Replace that instruction with chain_aoe_to_next_target, which
        # releases the next target's existing effect, cleans orphaned old
        # logical state, and then publishes its aoe_candidate_action marker as
        # the new action. The unchanged instructions after each hook copy the
        # AoE's retained slot and remaining effect state.
        for offset, source_genesis_sum, source_crc32_influence in (
            (0x004D14, 5169, 0xA3B91879),
            (0x004D8A, 5176, 0xB10C23E0),
            (0x0052F4, 5171, 0x11A68D47),
            (0x005470, 5179, 0xF7A37D36),
            (0x00563E, 5172, 0x0512B909),
        ):
            builder.replace(
                offset=offset,
                source_genesis_sum=source_genesis_sum,
                source_crc32_influence=source_crc32_influence,
                payload=bytes.fromhex(
                    f"4EB9{chain_aoe_to_next_target:08X}"  # JSR chain_aoe_to_next_target
                ),
            )

        # Issues 4 and 5: Before actor teardown, call
        # deallocate_attached_effect to clear an effect that might still be
        # attached to the actor and clean its logical state if now orphaned.
        builder.replace(
            offset=0x01E524,
            source_genesis_sum=2232,
            source_crc32_influence=0x7FFDD069,
            payload=bytes.fromhex(
                f"4EB9{deallocate_attached_effect:08X}"  # JSR attached-effect deallocator
            ),
        )


PATCH = Patch()
