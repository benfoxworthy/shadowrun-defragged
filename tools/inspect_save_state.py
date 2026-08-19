#!/usr/bin/env python3
"""Inspect an emulator save state for Defragged's build stamp and dice log."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


WORK_RAM_SIZE = 0x10000

STAMP_OFFSET = 0xF81C
STAMP_SIZE = 20
STAMP_PREFIX = b"Defragged "
HEADER_OFFSET = 0xF830
HEADER_SIZE = 8
NEXT_INDEX_OFFSET = HEADER_OFFSET
VALID_COUNT_OFFSET = HEADER_OFFSET + 1
FORMAT_VERSION_OFFSET = HEADER_OFFSET + 2
RECORD_SIZE_OFFSET = HEADER_OFFSET + 3
PATCH_CRC_OFFSET = HEADER_OFFSET + 4
ROM_CHECKSUM_OFFSET = HEADER_OFFSET + 6
RECORDS_OFFSET = 0xF838
RECORD_SIZE = 8
RECORD_COUNT = 54
FORMAT_VERSION = 1

# The logger captures the address immediately after each six-byte JSR to the
# shared dice routine. Keep these labels player-facing: the hexadecimal return
# address remains in the output for exact reverse-engineering attribution.
DICE_CALLER_NAMES = {
    0x000103B2: "Targeted spell attack",
    0x000125B8: "Medkit Biotech healing",
    0x0001856C: "Escape Black ICE while jacking out",
    0x000185AC: "Resist Black ICE dump shock",
    0x00019CA6: "Medic program repair",
    0x00021722: "Use Electronics on maglock",
    0x0002276E: "Fire on the prison guard post",
    0x000237C4: "Run from Lone Star",
    0x00023824: "Intimidate Eye-Fivers attacking a mage",
    0x00023932: "Calm the confused Mr. Johnson client",
    0x000239F4: "Assess the apparently injured man",
    0x00023AD4: "Assess the man following a woman",
    0x00023B1E: "Frighten away the woman's pursuer",
    0x00023B6C: "Menace the apparent undercover narc",
    0x00023B9A: "Confront the undercover Lone Star officer",
    0x00023BC6: "Assess the suspicious doctor-and-victim scene",
    0x00023C64: "Intimidate the doctor and assistants",
    0x0002429C: "Use Electronics on security terminal",
    0x000242B0: "Question the concerned man at the secure door",
    0x00024352: "Resist the spellcasting guard's badge check",
    0x00024444: "Talk past the ordinary security guard",
    0x00024494: "Talk past the spellcasting security guard",
    0x000244FC: "Avoid the hidden security camera",
    0x000245D4: "Jump over the pressure plate",
    0x00024602: "Stop before breaking the laser beams",
    0x0002467A: "React before security gets the drop on you",
    0x000246CE: "Subdue the woman before she raises the alarm",
    0x00024736: "Charm the corporate employee for information",
    0x000247E2: "Search the corporate computer database",
    0x00024854: "Shoot the fleeing Company Man",
    0x000248AC: "Impress the Company Man into sharing information",
    0x00024BE4: "Hide from a wilderness encounter",
    0x00024D56: "Search with the warriors for the lost arrowhead",
    0x000548F8: "Matrix node action",
    0x000556AA: "Firearm attack",
    0x000557DE: "Resist Stink/Confusion effect",
    0x00055892: "Thrown-weapon accuracy/scatter",
    0x000559CE: "Non-melee damage resistance",
    0x00055B40: "Hell Hound direct attack",
    0x00055CB4: "Melee attack",
    0x00055D1C: "Melee active defense",
    0x00055D98: "Melee damage resistance",
    0x00056034: "Matrix program initial test",
    0x00056098: "Matrix program opposing defense",
    0x000560E4: "Trace ICE initialization",
    0x00056162: "Escaped access/barrier ICE alert attack",
    0x000561A0: "Decker alert defense",
    0x0005629A: "Blaster/Killer/Black ICE attack",
    0x0005632A: "Deck defense against ICE attack",
    0x000563FE: "Trace-and-Burn ICE MPCP damage",
}


@dataclass(frozen=True)
class DiceRecord:
    slot: int
    caller: int
    frame: int
    dice: int
    target: int
    result: int


@dataclass(frozen=True)
class Diagnostics:
    stamp: str
    next_index: int
    valid_count: int
    format_version: int
    record_size: int
    patch_crc: int
    rom_checksum: int
    records: tuple[DiceRecord, ...]


def _decode_work_ram(ram: bytes) -> Diagnostics:
    raw_stamp = ram[STAMP_OFFSET : STAMP_OFFSET + STAMP_SIZE]
    stamp = raw_stamp.rstrip(b"\x00").decode("ascii", errors="replace")
    if not raw_stamp.startswith(STAMP_PREFIX):
        raise ValueError("state has no Defragged diagnostics stamp")

    next_index = ram[NEXT_INDEX_OFFSET]
    valid_count = ram[VALID_COUNT_OFFSET]
    format_version = ram[FORMAT_VERSION_OFFSET]
    record_size = ram[RECORD_SIZE_OFFSET]
    patch_crc = int.from_bytes(ram[PATCH_CRC_OFFSET : PATCH_CRC_OFFSET + 2], "big")
    rom_checksum = int.from_bytes(
        ram[ROM_CHECKSUM_OFFSET : ROM_CHECKSUM_OFFSET + 2], "big"
    )
    if format_version != FORMAT_VERSION or record_size != RECORD_SIZE:
        raise ValueError(
            f"unsupported diagnostics format {format_version}/{record_size}"
        )
    if next_index >= RECORD_COUNT or valid_count > RECORD_COUNT:
        raise ValueError("corrupt diagnostics circular-log header")

    first = next_index if valid_count == RECORD_COUNT else 0
    records: list[DiceRecord] = []
    for sequence in range(valid_count):
        slot = (first + sequence) % RECORD_COUNT
        offset = RECORDS_OFFSET + slot * RECORD_SIZE
        record = ram[offset : offset + RECORD_SIZE]
        records.append(
            DiceRecord(
                slot=slot,
                caller=int.from_bytes(record[0:4], "big"),
                frame=record[4],
                dice=record[5],
                target=record[6],
                result=record[7],
            )
        )
    return Diagnostics(
        stamp=stamp,
        next_index=next_index,
        valid_count=valid_count,
        format_version=format_version,
        record_size=record_size,
        patch_crc=patch_crc,
        rom_checksum=rom_checksum,
        records=tuple(records),
    )


def decode_state(data: bytes) -> Diagnostics:
    """Find a contiguous 64 KiB work-RAM image and decode its diagnostics."""

    candidates: list[Diagnostics] = []
    search_from = 0
    while True:
        stamp_position = data.find(STAMP_PREFIX, search_from)
        if stamp_position < 0:
            break
        search_from = stamp_position + 1
        work_ram_start = stamp_position - STAMP_OFFSET
        work_ram_end = work_ram_start + WORK_RAM_SIZE
        if work_ram_start < 0 or work_ram_end > len(data):
            continue
        try:
            candidates.append(_decode_work_ram(data[work_ram_start:work_ram_end]))
        except ValueError:
            continue

    if not candidates:
        raise ValueError(
            "state has no Defragged diagnostics stamp in contiguous 68000 work RAM"
        )
    if len(candidates) > 1:
        raise ValueError("state contains multiple Defragged diagnostics logs")
    return candidates[0]


def _input(value: int) -> str:
    return "255+" if value == 0xFF else str(value)


def render(diagnostics: Diagnostics) -> str:
    lines = [
        diagnostics.stamp,
        (
            f"format={diagnostics.format_version} record_size={diagnostics.record_size} "
            f"retained={diagnostics.valid_count}/{RECORD_COUNT} "
            f"patch_crc={diagnostics.patch_crc:04X} "
            f"rom_checksum={diagnostics.rom_checksum:04X}"
        ),
        "seq slot frame  dF caller    dice  TN result  event",
    ]
    previous_frame: int | None = None
    for sequence, record in enumerate(diagnostics.records):
        delta = (
            "--"
            if previous_frame is None
            else str((record.frame - previous_frame) & 0xFF)
        )
        lines.append(
            f"{sequence:3d} {record.slot:4d}   {record.frame:02X} "
            f"{delta:>3} {record.caller:08X} "
            f"{_input(record.dice):>5} {_input(record.target):>3} "
            f"{record.result:6d}  "
            f"{DICE_CALLER_NAMES.get(record.caller, 'Unknown dice test')}"
        )
        previous_frame = record.frame
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path, help="emulator save-state file")
    args = parser.parse_args()
    try:
        diagnostics = decode_state(args.state.read_bytes())
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(render(diagnostics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
