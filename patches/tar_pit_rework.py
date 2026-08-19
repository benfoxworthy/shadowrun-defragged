"""Rework Tar Pit to disable a program instead of delete it

Tar Pit permanently deletes a program. That is faithful to the tabletop game,
but unusually harsh as it makes you re-buy lost programs and leads to
save-scumming. Tar Paper already demonstrates a fairer shape: unload the
program and force the decker to adapt.

This rework keeps Tar Pit much more forgiving (but still scarier than Tar
Paper) by unloading the program and blocking it for the rest of the current
Matrix run. This can still end a run if the player doesn't have an alternative
Attack program, but doesn't cost money or force a trip to the shop.

A "tarred" program is displayed with a frame of the Tar animation on top of it
to indicate that it's unusable. This clears after jacking out of the Matrix.

Before:

    owned_program_rank[program_id] = 0  # permanent deletion
    unload_program_from_active_slot()

Patch:

    tarred_program_mask |= 1 << program_id
    unload_program_from_active_slot()
    reject_loads_while_bit_is_set()
    clear_mask_when_the_complete_matrix_session_ends()

The mask is keyed by the twelve program IDs rather than the five loaded slots,
so several victims can remain disabled while their slots are reused. The
cyberdeck grid overlays the stock Tar sprite on each blocked program. Tar Paper
still performs only the stock unload. See ``tar_pit_rework_research.md`` for
the RAM audit, grid/palette work, and lifecycle trace.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


PROGRAM_MASK = 0xE0FE  # Statically audited unused RAM word between $FFE0FC and $FFE100
OVERLAY_FRAME = 0x0001DB60  # Existing Tar animation Frame 02 sprite
APPEND_SPRITE = 0x00001378
EXIT_CLEANUP = 0x00053126
REJECTED_LOAD_RETURN = 0x00019430


class Patch(PatchSpec):
    id = "tar-pit-rework"
    description = (
        "Tar Pit no longer permanently deletes a program. Instead, the program is removed from "
        "memory and cannot be reloaded until the current Matrix run ends."
    )
    category = "Tar Pit & Deck Storage Rework"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Mark the affected program as unavailable for this Matrix session.
        # The twelve-bit mask is keyed by program ID, not by the five loaded slots.
        #
        # tarred_program_mask |= 1 << affected_program_id
        tar_pit_mark_program_helper_address = builder.add_cave(
            bytes.fromhex(
                "7205"                     # MOVEQ #5,D1 (preserve Tar Pit subtype)
                f"3438{PROGRAM_MASK:04X}"  # MOVE.W (Tar mask).W,D2
                "01C2"                     # BSET D0,D2
                f"31C2{PROGRAM_MASK:04X}"  # MOVE.W D2,(Tar mask).W
                "4E75"                     # RTS
            )
        )

        # Draw a Tar overlay on every unavailable program in the 4x3 deck grid.
        #
        # append_cursor()
        # for program_id in 0..11:
        #     if tarred_program_mask & (1 << program_id):
        #         append_tar_overlay(program_grid_cell[program_id])
        tar_pit_cyberdeck_overlay_helper_address = builder.add_cave(
            bytes.fromhex(
                "4278D880"                  # CLR.W ($D880).W (palette index 1: black)
                "31FC0022D882"              # MOVE.W #$0022,($D882).W (dark brown)
                "31FC0024D88A"              # MOVE.W #$0024,($D88A).W (brown)
                f"4EB8{APPEND_SPRITE:04X}"  # JSR append_sprite
                f"3638{PROGRAM_MASK:04X}"   # MOVE.W (Tar mask).W,D3
                "7C00"                      # MOVEQ #0,D6 (dedicated Tar palette)
                "343C00A7"                  # MOVE.W #$00A7,D2 (frame offset lands at first row)
                "7E02"                      # MOVEQ #2,D7 (three rows)
                "7803"                      # row: MOVEQ #3,D4 (four columns)
                "323C0090"                  # MOVE.W #$0090,D1 (program origin, not cursor border)
                "E24B"                      # cell: LSR.W #1,D3
                "640A"                      # BCC.S skip
                f"45F9{OVERLAY_FRAME:08X}"  # LEA Tar overlay frame 02,A2
                f"4EB8{APPEND_SPRITE:04X}"  # JSR append_sprite
                "06410020"                  # skip: ADDI.W #$20,D1
                "51CCFFEC"                  # DBF D4,cell
                "06420028"                  # ADDI.W #$28,D2
                "51CFFFDE"                  # DBF D7,row
                "4E75"                      # RTS
            )
        )

        # Make every temporarily disabled program available when the run ends.
        tar_pit_matrix_exit_helper_address = builder.add_cave(
            bytes.fromhex(
                f"4278{PROGRAM_MASK:04X}"  # CLR.W (Tar mask).W
                f"4EF9{EXIT_CLEANUP:08X}"  # JMP displaced Matrix-exit cleanup
            )
        )

        # Reject a program load when the program is unowned or temporarily tarred.
        #
        # if program_is_tarred(selected_program) or not program_is_owned:
        #     skip_the_stock_load_path()
        tar_pit_program_load_helper_address = builder.add_cave(
            bytes.fromhex(
                f"3238{PROGRAM_MASK:04X}"          # MOVE.W (Tar mask).W,D1
                "0F01"                             # BTST D7,D1
                "6606"                             # BNE.S rejected
                "4A31700E"                         # TST.B $E(A1,D7.W) (ownership)
                "6606"                             # BNE.S loadable
                f"2EBC{REJECTED_LOAD_RETURN:08X}"  # rejected: MOVE.L #skip_load,(A7) (new return)
                "4E75"                             # loadable: RTS
            )
        )

        # Clear all temporary Tar marks before resuming stock Matrix-exit cleanup.
        builder.replace(
            offset=0x0176B2,
            source_genesis_sum=32740,
            source_crc32_influence=0x9E926C1A,
            payload=bytes.fromhex(
                "4EB9"  # JSR absolute-long
                f"{tar_pit_matrix_exit_helper_address}"
            ),
        )

        # Replay the stock cursor append, then draw Tar overlays in the deck menu.
        builder.replace(
            offset=0x0182CA,
            source_genesis_sum=25137,
            source_crc32_influence=0x29162E71,
            payload=bytes.fromhex(
                "4EB9"  # JSR absolute-long
                f"{tar_pit_cyberdeck_overlay_helper_address}"
            ),
        )

        # Replace the tar pit program load gate with the new decision logic.
        builder.replace(
            offset=0x019242,
            source_genesis_sum=74535,
            source_crc32_influence=0x2B5F23DB,
            payload=bytes.fromhex(
                "4EB9"  # JSR absolute-long
                f"{tar_pit_program_load_helper_address}"
                "4E71"  # NOP
            ),
        )

        # Mark the affected program before the stock Tar Pit unload continues.
        builder.replace(
            offset=0x019AC2,
            source_genesis_sum=29824,
            source_crc32_influence=0x76398035,
            payload=bytes.fromhex(
                "4EB9"  # JSR absolute-long
                f"{tar_pit_mark_program_helper_address}"
                "4E71"  # NOP
            ),
        )


PATCH = Patch()
