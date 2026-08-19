"""Identify the running build and retain a compact recent dice-roll history.

Shadowrun resolves attacks, damage resistance, spell effects, dialogue tests,
and many other events through one shared exploding-d6 success-test routine.
The random variation makes small changes such as one target number or three
extra resistance dice difficult to verify by eye.  This patch records each use
of that routine, turning otherwise unused work RAM into a primitive combat log
for the preceding few frames.  The caller address identifies what kind of test
occurred, while the inputs and result show what the game actually rolled.

The stock save-staging buffer has 460 checksum-excluded padding bytes at
``$FFF81C..$FFF9E7``.  The patch refreshes the build stamp every frame and uses
the rest for a versioned circular log::

    Address range       Size  Contents
    $FFF81C..$FFF82F      20  "Defragged SSSS-PPPP\0"
    $FFF830..$FFF837       8  log header
    $FFF838..$FFF9E7     432  54 eight-byte records

``SSSS`` is the final 16-bit Genesis header checksum read from the running ROM.
``PPPP`` is a CRC-16/CCITT fingerprint of the complete resolved patch edit
plan, calculated while the stamp's own ASCII and binary CRC fields are zero.

The eight-byte log header uses this exact big-endian schema::

    Offset  Size  Field
      +0      1   next record index (0..53)
      +1      1   number of valid records (0..54)
      +2      1   format version (1)
      +3      1   record size (8)
      +4      2   binary patch CRC (PPPP)
      +6      2   Genesis header checksum (SSSS)

Each eight-byte record uses this exact big-endian schema::

    Offset  Size  Field
      +0      4   return address of the dice-test caller
      +4      1   low byte of the frame counter
      +5      1   input dice count, saturated to $FF
      +6      1   input target number, saturated to $FF
      +7      1   number of successes returned by the stock routine

Fifty-four records is simply as many as fit in the unused memory after the
stamp and header.  Matching frame bytes group tests made during the same frame;
their modulo-256 differences also make the timing between nearby events clear.
The log survives in emulator save states that contain the 68000 work RAM.  Use
``python tools/inspect_save_state.py <state>`` to locate it, restore circular
records to chronological order, and translate known caller addresses into
human-readable event names.
"""

from __future__ import annotations

import binascii

from patch_framework import Edit, PatchBuilder, PatchSpec


STAMP_START = 0x00FFF81C
STAMP_SIZE = 20
LOG_HEADER = 0x00FFF830
LOG_RECORDS = 0x00FFF838
LOG_RECORD_SIZE = 8
LOG_RECORD_COUNT = 54
LOG_END = 0x00FFF9E8
LOG_FORMAT_VERSION = 1
LOG_FORMAT_WORD = (LOG_FORMAT_VERSION << 8) | LOG_RECORD_SIZE

LOG_NEXT_INDEX = LOG_HEADER
LOG_VALID_COUNT = LOG_HEADER + 1
LOG_FORMAT_AND_SIZE = LOG_HEADER + 2
LOG_PATCH_CRC = LOG_HEADER + 4
LOG_ROM_CHECKSUM = LOG_HEADER + 6

FRAME_COUNTER_LOW_BYTE = 0x00FFF9EF
DICE_TEST_SUCCESSES = 0x00FFF0DD
GENESIS_HEADER_CHECKSUM = 0x0000018E

VBLANK_UPDATE_CALL = 0x00001074
STOCK_VBLANK_UPDATE = 0x00001872
ROLL_DICE_POOL_SUCCESS_TEST = 0x00000DBA
STOCK_DICE_CONTINUE = 0x00000DC0

STAMP_TEMPLATE_PREFIX = b"Defragged 0000-"
STAMP_PATCH_CRC_OFFSET = 15
STAMP_TEMPLATE_SUFFIX = b"\x00"
TEMPLATE_BINARY_CRC_OFFSET = STAMP_SIZE


class Patch(PatchSpec):
    id = "defragged-diagnostics"
    description = (
        "Stamps the exact Defragged build in RAM and retains a log of the most "
        "recent dice tests for save state diagnostics."
    )
    category = "Attribution/Diagnostics"
    finalize_priority = 100

    def __init__(self) -> None:
        self._template_address: int | None = None

    def build_patch(self, builder: PatchBuilder) -> None:
        readable_template = STAMP_TEMPLATE_PREFIX + b"0000" + STAMP_TEMPLATE_SUFFIX
        if len(readable_template) != STAMP_SIZE:
            raise ValueError("diagnostic stamp template must remain 20 bytes")
        template = readable_template + b"\x00\x00"
        template_address = builder.add_cave(template)
        self._template_address = template_address

        stamp_writer = builder.add_cave(_stamp_writer(template_address))
        frame_wrapper = builder.add_cave(_frame_wrapper(stamp_writer))
        dice_post_logger = builder.add_cave(_dice_post_logger())
        dice_entry_logger = builder.add_cave(
            _dice_entry_logger(template_address, dice_post_logger)
        )

        builder.replace(
            offset=VBLANK_UPDATE_CALL,
            source_genesis_sum=26411,
            source_crc32_influence=0x9A501667,
            payload=bytes.fromhex(
                f"4EB9{frame_wrapper:08X}"  # JSR frame_wrapper
            ),
        )
        builder.replace(
            offset=ROLL_DICE_POOL_SUCCESS_TEST,
            source_genesis_sum=103469,
            source_crc32_influence=0x081FA566,
            payload=bytes.fromhex(
                f"4EF9{dice_entry_logger:08X}"  # JMP dice_entry_logger
            ),
        )

    def finalize_patch(self, builder: PatchBuilder) -> None:
        if self._template_address is None:
            raise RuntimeError("diagnostic stamp template was not allocated")
        crc = _patch_crc16(builder.edits)
        builder.rewrite_cave(
            self._template_address + STAMP_PATCH_CRC_OFFSET,
            f"{crc:04X}".encode("ascii"),
        )
        builder.rewrite_cave(
            self._template_address + TEMPLATE_BINARY_CRC_OFFSET,
            crc.to_bytes(2, "big"),
        )


def _patch_crc16(edits: list[Edit]) -> int:
    """Fingerprint resolved offsets, lengths, and replacement payloads."""

    crc = binascii.crc_hqx(b"Shadowrun Defragged patch edits v1\x00", 0xFFFF)
    for edit in sorted(edits, key=lambda item: item.offset):
        crc = binascii.crc_hqx(edit.offset.to_bytes(4, "big"), crc)
        crc = binascii.crc_hqx(len(edit.payload).to_bytes(4, "big"), crc)
        crc = binascii.crc_hqx(edit.payload, crc)
    return crc


def _stamp_writer(template_address: int) -> bytes:
    """Rewrite the build stamp without disturbing the log or its header."""

    # Copy "Defragged 0000-PPPP\0", retain the binary Genesis checksum,
    # and render that checksum backward into the four zero placeholders.
    #
    # memcpy(STAMP_START, template_address, STAMP_SIZE);
    # checksum = *(uint16_t *)GENESIS_HEADER_CHECKSUM;
    # for (int digit = 3; digit >= 0; --digit) {
    #     STAMP_START[10 + digit] = hex_ascii(checksum & 0xF);
    #     checksum >>= 4;
    # }
    return bytes.fromhex(
        f"43F9{template_address:08X}"  # LEA ROM template,A1
        f"41F9{STAMP_START:08X}"  # LEA RAM stamp,A0
        "7204"  # MOVEQ #4,D1: copy five longwords
        "20D9"  # copy_stamp: MOVE.L (A1)+,(A0)+
        "51C9FFFC"  # DBF D1,copy_stamp
        f"3038{GENESIS_HEADER_CHECKSUM:04X}"  # MOVE.W $018E,D0
        f"41F9{STAMP_START + 14:08X}"  # LEA one byte past SSSS,A0
        "7203"  # MOVEQ #3,D1: four hexadecimal digits
        "3400"  # hex_digit: MOVE.W D0,D2
        "0242000F"  # ANDI.W #$000F,D2
        "0C020009"  # CMPI.B #9,D2
        "6304"  # BLS.S decimal
        "06020007"  # ADDI.B #7,D2: A-F adjustment
        "06020030"  # decimal: ADDI.B #'0',D2
        "1102"  # MOVE.B D2,-(A0)
        "E848"  # LSR.W #4,D0
        "51C9FFE6"  # DBF D1,hex_digit
        "4E75"  # RTS
    )


def _frame_wrapper(stamp_writer: int) -> bytes:
    """Run the complete stock VBlank update, then refresh the build stamp."""

    # stock_vblank_update();
    # return stamp_writer();
    return bytes.fromhex(
        f"4EB9{STOCK_VBLANK_UPDATE:08X}"  # JSR stock VBlank update
        f"4EF9{stamp_writer:08X}"  # JMP stamp_writer; tail return to interrupt
    )


def _dice_entry_logger(template_address: int, post_logger: int) -> bytes:
    """Record inputs, then enter the untouched stock dice-test body."""

    # The synthetic return sits below the stock D0-D4 save frame. The stock
    # epilogue therefore restores those registers and returns to post_logger,
    # where A0 still points at the result byte: neither the stock dice body nor
    # random_below touches A0.
    #
    # save(D5_A0);
    # push_return_address(post_logger);
    # stock_save(D0_D4);
    # if (header.patch_crc != template.patch_crc ||
    #     header.rom_checksum != ROM_HEADER_CHECKSUM ||
    #     header.format_and_size != 0x0108) {
    #     header = {0, 0, 0x0108, template.patch_crc, ROM_HEADER_CHECKSUM};
    # }
    # record = records[next_index];
    # record->caller = caller_return_address;
    # record->frame = vblank_tick & 0xFF;
    # record->dice = saturate_u8(D6);
    # record->target = saturate_u8(D4);
    # --D6;
    # goto STOCK_DICE_CONTINUE;
    return bytes.fromhex(
        "48E70480"  # MOVEM.L D5/A0,-(A7): preserve stock-untouched registers
        f"4879{post_logger:08X}"  # PEA post_logger: synthetic stock return
        "48E7F800"  # MOVEM.L D0-D4,-(A7): displaced stock prologue
        f"3039{template_address + TEMPLATE_BINARY_CRC_OFFSET:08X}"  # ROM CRC
        f"3238{GENESIS_HEADER_CHECKSUM:04X}"  # MOVE.W $018E,D1
        f"B079{LOG_PATCH_CRC:08X}"  # CMP.W header patch CRC,D0
        "6612"  # BNE.S initialize_header
        f"B279{LOG_ROM_CHECKSUM:08X}"  # CMP.W header ROM checksum,D1
        "660A"  # BNE.S initialize_header
        f"0C79{LOG_FORMAT_WORD:04X}{LOG_FORMAT_AND_SIZE:08X}"  # format/size
        "671A"  # BEQ.S header_ready
        f"4279{LOG_HEADER:08X}"  # initialize_header: CLR.W index/count
        f"33FC{LOG_FORMAT_WORD:04X}{LOG_FORMAT_AND_SIZE:08X}"  # format/size
        f"33C0{LOG_PATCH_CRC:08X}"  # MOVE.W D0,header patch CRC
        f"33C1{LOG_ROM_CHECKSUM:08X}"  # MOVE.W D1,header ROM checksum
        "7000"  # header_ready: MOVEQ #0,D0
        f"1039{LOG_NEXT_INDEX:08X}"  # MOVE.B next_index,D0
        "E748"  # LSL.W #3,D0: eight-byte record stride
        f"41F9{LOG_RECORDS:08X}"  # LEA records,A0
        "D0C0"  # ADDA.W D0,A0
        "20EF0020"  # MOVE.L $20(A7),(A0)+: original caller return
        f"10F9{FRAME_COUNTER_LOW_BYTE:08X}"  # MOVE.B frame,(A0)+
        "3006"  # MOVE.W D6,D0: input dice
        "0C4000FF"  # CMPI.W #$00FF,D0
        "6302"  # BLS.S dice_fits
        "70FF"  # MOVEQ #$FF,D0: overflow sentinel
        "10C0"  # dice_fits: MOVE.B D0,(A0)+
        "3004"  # MOVE.W D4,D0: target number
        "0C4000FF"  # CMPI.W #$00FF,D0
        "6302"  # BLS.S target_fits
        "70FF"  # MOVEQ #$FF,D0: overflow sentinel
        "10C0"  # target_fits: MOVE.B D0,(A0)+
        "5346"  # SUBQ.W #1,D6: second displaced stock instruction
        f"4EF9{STOCK_DICE_CONTINUE:08X}"  # JMP untouched stock dice body
    )


def _dice_post_logger() -> bytes:
    """Commit the stock result and return to the original dice-test caller."""

    # stock_dice_test_returned_with(D0_D4_restored);
    # preserve(D0, CCR);
    # record->result = dice_test_successes;
    # next_index = (next_index + 1) % LOG_RECORD_COUNT;
    # valid_count = min(valid_count + 1, LOG_RECORD_COUNT);
    # restore(D0, CCR, D5_A0);
    # return;
    return bytes.fromhex(
        "40C5"  # MOVE.W SR,D5: preserve stock result flags
        "2F00"  # MOVE.L D0,-(A7): preserve stock-restored D0
        f"10B9{DICE_TEST_SUCCESSES:08X}"  # MOVE.B successes,(A0)
        "7000"  # MOVEQ #0,D0
        f"1039{LOG_NEXT_INDEX:08X}"  # MOVE.B next_index,D0
        "5200"  # ADDQ.B #1,D0
        f"0C0000{LOG_RECORD_COUNT:02X}"  # CMPI.B #54,D0
        "6502"  # BCS.S index_ready
        "4200"  # CLR.B D0: wrap 54 to zero
        f"13C0{LOG_NEXT_INDEX:08X}"  # index_ready: MOVE.B D0,next_index
        f"0C3900{LOG_RECORD_COUNT:02X}{LOG_VALID_COUNT:08X}"  # count vs 54
        "6406"  # BCC.S count_full
        f"5239{LOG_VALID_COUNT:08X}"  # ADDQ.B #1,valid_count
        "201F"  # count_full: MOVE.L (A7)+,D0
        "44C5"  # MOVE.W D5,CCR
        "4CDF0120"  # MOVEM.L (A7)+,D5/A0
        "4E75"  # RTS to original dice-test caller
    )


PATCH = Patch()
