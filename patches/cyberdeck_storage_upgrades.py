"""Rework cyberdeck storage upgrade limits

This started as fallout from ``tar-pit-rework``. Tar Pit no longer deletes
programs permanently—which is much less harsh—but that also removes the
game's only way to discard a bad program. A deck filled with obsolete software
could become mildly stuck, with too little free storage to buy the programs
the player actually wants.

Before: The stock rule is approximately:

    if deck.total_storage >= deck.mpcp * 80:
        refuse_upgrade()
    else:
        deck.total_storage += 25

Because it compares *total* storage without accounting for the deck's built-in
base, some models begin at or above their cap and can never upgrade. The
80-MP cap interval and 25-MP purchase interval also do not divide evenly, so a
legal purchase can overshoot the nominal cap.

Patch: Give every model a clean allowance of ``2 * MPCP`` upgrades above
its own base storage. Each upgrade adds 50 MP: large enough to avoid twenty-four
tedious menu purchases, but still granular enough to matter. Prices rise from
200¥ by 150¥ per rank so the extra room is convenient rather than trivial.
The Excalibur begins at 1,250 MP and tops out at 2,450 MP, enough for every
program at maximum rank plus datafiles.

Legacy decks are handled deliberately: old 25-MP half-steps complete on the
next purchase, and an old 1,000-MP Excalibur remains upgradeable without a save
migration. See ``cyberdeck_storage_upgrades_research.md`` for the model table,
the discarded alternatives, and the arithmetic behind these values.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


DECK_RECORDS = 0x001AB196  # Start of the canonical cyberdeck shop records
DRAW_ENCODED_TEXT = 0x0000C0DA
DRAW_DECIMAL_NUMBER = 0x0000C216
STORAGE_LEFT_PROMPT = 0x001AB61E
STORAGE_COST_SUFFIX = 0x001AB62E
INCREASE_SUFFIX = 0x001AB5B1
MAXIMUM_UPGRADE_PROMPT = 0x001AA50E


class Patch(PatchSpec):
    id = "cyberdeck-storage-upgrades"
    description = (
        "Deck Storage Refactor: Because Tar Pit no longer permanently deletes programs when "
        "using the 'tar-pit-rework' patch, this patch expands storage upgrades to prevent "
        "getting stuck with a deck full of unwanted programs. Every deck can now receive "
        "Storage upgrades equal to twice its MPCP rating; each upgrade adds 50 MP instead of 25 "
        "MP; costs increase with each upgrade; and the Fairlight Excalibur starts with 1,250 MP "
        "and can reach 2,450 MP (enough to hold all programs at max rank)."
    )
    category = "Tar Pit & Deck Storage Rework"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Shared, side-effect-free calculation used by both the purchase and
        # tooltip paths. Input: A0 = current deck. Output: D1 = next price;
        # the final CMP flags report whether the rank cap has been reached.
        # D0-D3/A1 are scratch registers.
        storage_upgrade_calculator_address = builder.add_cave(
            bytes.fromhex(
                "7000"                         # MOVEQ #0,D0
                "1010"                         # MOVE.B (A0),D0 (MPCP)
                "D040"                         # ADD.W D0,D0 (rank cap = MPCP * 2)
                "7400"                         # MOVEQ #0,D2
                "1428000D"                     # MOVE.B $D(A0),D2 (model ID)
                "4A02"                         # TST.B D2
                "6A02"                         # BPL.S model_is_valid
                "4242"                         # CLR.W D2 (legacy $FF is model 0)
                "C4FC000E"                     # MULU.W #14,D2
                f"43F9{DECK_RECORDS:08X}"      # LEA cyberdeck records,A1
                "3431200A"                     # MOVE.W $A(A1,D2.W),D2 (base)
                "36280004"                     # MOVE.W $4(A0),D3 (storage)
                "9642"                         # SUB.W D2,D3
                "48C3"                         # EXT.L D3
                "87FC0032"                     # DIVS.W #50,D3 (upgrade rank)
                "3203"                         # MOVE.W D3,D1
                "4A41"                         # TST.W D1
                "6A02"                         # BPL.S nonnegative_rank
                "4241"                         # CLR.W D1 (negative ranks use floor)
                "C2FC0096"                     # MULU.W #150,D1
                "064100C8"                     # ADDI.W #200,D1 (next price)
                "B043"                         # CMP.W D3,D0 (cap flags)
                "4E75"                         # RTS
            )
        )

        # Extend the stock hardware-description renderer only for Storage.
        # Preserve the complete register contract of the original text draw;
        # notably, the next title draw relies on D1 still containing $6000.
        # The extra lines use the stock decimal renderer for the live price.
        # Capped decks quote no phantom price.
        storage_tooltip_renderer_address = builder.add_cave(
            bytes.fromhex(
                "48E7F0F0"                     # MOVEM.L D0-D3/A0-A3,-(A7)
                "40E7"                         # MOVE.W SR,-(A7)
                f"267C{DRAW_ENCODED_TEXT:08X}" # MOVEA.L #text renderer,A3
                "4E93"                         # JSR (A3): original description
                "0C39000100FFF0D0"             # CMPI.B #1,$FFF0D0 (Storage?)
                "6708"                         # BEQ.S storage
                "46DF"                         # MOVE.W (A7)+,SR
                "4CDF0F0F"                     # MOVEM.L (A7)+,D0-D3/A0-A3
                "4E75"                         # RTS (other hardware tooltip)
                "41F8FBBE"                     # LEA ($FBBE).W,A0 (current deck)
                f"4EB9{storage_upgrade_calculator_address}"  # JSR calculator
                "6F4C"                         # BLE.S maximum
                "3601"                         # MOVE.W D1,D3 (save price)
                f"43F9{STORAGE_LEFT_PROMPT:08X}"
                "247C0000C606"                 # MOVEA.L #$C606,A2
                "323C6000"                     # MOVE.W #$6000,D1
                "4E93"                         # JSR (A3): left-margin lines
                "247C0000C61A"                 # MOVEA.L #$C61A,A2 (3-digit price)
                "0C4303E8"                     # CMPI.W #1000,D3
                "6502"                         # BCS.S draw_price
                "588A"                         # ADDQ.L #4,A2 (4 digits plus comma)
                "2203"                         # MOVE.L D3,D1
                "343C6000"                     # MOVE.W #$6000,D2
                f"4EB9{DRAW_DECIMAL_NUMBER:08X}"  # JSR draw dynamic price
                "548A"                         # ADDQ.L #2,A2
                f"43F9{STORAGE_COST_SUFFIX:08X}"
                "323C6000"                     # MOVE.W #$6000,D1
                "4E93"                         # JSR (A3): currency and suffix
                f"43F9{INCREASE_SUFFIX:08X}"
                "247C0000C692"                 # MOVEA.L #$C692,A2
                "4E93"                         # JSR (A3): "increase."
                "6012"                         # BRA.S done
                f"43F9{MAXIMUM_UPGRADE_PROMPT:08X}"  # maximum: LEA stock text,A1
                "247C0000C606"                 # MOVEA.L #$C606,A2
                "323C6000"                     # MOVE.W #$6000,D1
                "4E93"                         # JSR (A3): maximum text
                "46DF"                         # done: MOVE.W (A7)+,SR
                "4CDF0F0F"                     # MOVEM.L (A7)+,D0-D3/A0-A3
                "4E75"                         # RTS
            )
        )

        # End the stock Storage string after its general description, then
        # reuse its obsolete flat-price bytes for the dynamic-price prompt.
        # The replacement fits the original string's allocation exactly.
        builder.replace(
            offset=0x1AB61D,
            source_genesis_sum=375926,
            source_crc32_influence=0x37F0D0FB,
            payload=(
                b"\xFF"  # End the four-line description
                b"Cost is \x8050 Mp \xFF"
                b"$ for the next\xFF"
                + b"\xFF" * 3
            ),
        )

        # Route the common description draw through the Storage-aware wrapper.
        builder.replace(
            offset=0x058348,
            source_genesis_sum=69523,
            source_crc32_influence=0xBF77FB8F,
            payload=bytes.fromhex(
                f"4EB9{storage_tooltip_renderer_address}"  # JSR tooltip wrapper
            ),
        )

        # Normalize legacy decks with no model ID before calculating upgrades.
        builder.replace(
            offset=0x05768C,
            source_genesis_sum=272546,
            source_crc32_influence=0x4DC50C72,
            payload=bytes.fromhex(
                "1238F0D0"  # MOVE.B ($F0D0).W,D1
                "41F8FBBE"  # LEA ($FBBE).W,A0
                "4280"      # CLR.L D0
                "1010"      # MOVE.B (A0),D0
                "0C410002"  # CMPI.W #2,D1
                "6764"      # BEQ.S original destination
                "6E2E"      # BGT.S original destination
                "4A41"      # TST.W D1
                "6750"      # BEQ.S original destination
                "4A28000D"  # TST.B $D(A0)
                "6A04"      # BPL.S model_is_valid
                "4228000D"  # CLR.B $D(A0) (normalize legacy $FF to model 0)
            ),
        )

        # Replace the stock flat cap and price calculation with the helper.
        builder.replace(
            offset=0x0576AE,
            source_genesis_sum=94648,
            source_crc32_influence=0x8987820C,
            payload=bytes.fromhex(
                f"4EB9{storage_upgrade_calculator_address}"  # JSR calculator
                "6E5C"  # BGT.S $057712 (allowed: dynamic price is in D1)
            ),
        )

        # Make Storage purchases add 50 MP while preserving legacy half-steps.
        #
        # amount = 25 if deck.storage is 25 MP short of alignment else 50
        # deck.storage += amount
        builder.replace(
            offset=0x05777E,
            source_genesis_sum=436026,
            source_crc32_influence=0x5E2E2CFD,
            payload=bytes.fromhex(
                "43F8FBBE"      # LEA ($FBBE).W,A1
                "4A38F0D0"      # TST.B ($F0D0).W
                "6710"          # BEQ.S Body upgrade
                "0C380002F0D0"  # CMPI.B #2,($F0D0).W
                "6B10"          # BMI.S Storage upgrade
                "6722"          # BEQ.S Persona upgrade
                "52290007"      # ADDQ.B #1,$7(A1) (Response)
                "4E75"          # RTS
                "0669000A0002"  # Body: ADDI.W #10,$2(A1)
                "4E75"          # RTS
                "7019"          # Storage: MOVEQ #25,D0
                "082900000005"  # BTST #0,$5(A1) (low storage byte)
                "6602"          # BNE.S add_storage (legacy 25-MP half-step)
                "D040"          # ADD.W D0,D0 (normal 50-MP step)
                "D1690004"      # add_storage: ADD.W D0,$4(A1)
                "4E75"          # RTS
                "4E71"          # Alignment NOP
                "5A290006"      # Persona: ADDQ.B #5,$6(A1)
                "4E75"          # RTS
            ),
        )

        # Raise the Fairlight Excalibur's starting Storage to 1,250 MP.
        builder.replace(
            offset=0x1AB21E,
            source_genesis_sum=1000,
            source_crc32_influence=0xB12743EA,
            payload=bytes.fromhex(
                "04E2"  # DC.W $03E8 -> DC.W $04E2
            ),
        )

        # Mirror model 3's split-table base into an unused sentinel record so
        # the compact helper can use one linear five-model lookup.
        builder.replace(
            offset=0x1AB1CA,
            source_genesis_sum=65535,
            source_crc32_influence=0xA656495B,
            payload=bytes.fromhex(
                "03E8"  # DC.W $FFFF -> DC.W $03E8 at first-block sentinel record 3 +$A
            ),
        )

        # Mirror model 4's split-table base into the same linear lookup.
        builder.replace(
            offset=0x1AB1D8,
            source_genesis_sum=65535,
            source_crc32_influence=0x7DB9FE84,
            payload=bytes.fromhex(
                "04E2"  # DC.W $FFFF -> DC.W $04E2 at first-block sentinel record 4 +$A
            ),
        )

        # Give the starter cyberdeck an explicit model-0 ID.
        builder.replace(
            offset=0x14C201,
            source_genesis_sum=255,
            source_crc32_influence=0xE7F262D9,
            payload=bytes.fromhex(
                "00"  # DC.B $FF -> DC.B $00 at cyberdeck record +$D
            ),
        )


PATCH = Patch()
