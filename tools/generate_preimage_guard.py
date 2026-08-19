#!/usr/bin/env python3
r"""Generate non-literal source metadata for one fixed ROM patch edit.

Shadowrun Defragged deliberately avoids tracking even small excerpts of the
original Shadowrun ROM. A fixed edit still needs to prove that it is replacing
the intended source instruction or data, and the builder needs enough
information to derive the patched Genesis checksum and BPS target CRC without
reading or embedding the original ROM.

For the source range selected by ``offset`` and the replacement payload's
length, this tool reads a user-supplied local ROM and emits only:

* the source range's contribution to the Genesis checksum; and
* its affine CRC-32 influence, used both for supplied-ROM validation and
  ROM-free BPS checksum calculation.

These values do not contain the source bytes. They are publication hygiene,
not a secrecy mechanism: the CRC-32 influence of a one- or two-byte range can
naturally be brute-forced. No separate length is stored because fixed edits are
length-preserving, so the source range length is derived from the replacement
payload passed to ``builder.replace(...)``.

Example (PowerShell)::

    python tools\generate_preimage_guard.py `
      "path\to\Shadowrun (USA).gen" `
      0x0104F8 `
      7807

The final argument is the replacement byte sequence, not the original bytes.
The command prints two keyword arguments. Paste them directly into the
corresponding ``builder.replace(...)`` call, between ``offset`` and ``payload``::

    builder.replace(
        offset=0x0104F8,
        source_genesis_sum=...,
        source_crc32_influence=0x...,
        payload=bytes.fromhex("7807"),
    )

Keeping the guard inline makes the source assumptions for an edit visible next
to its replacement. The required keyword arguments also prevent a fixed edit
from being added without a guard. Builds made without a ROM use the checksum
influences to produce the same deterministic BPS file; builds made with a ROM
also verify each actual source range using its CRC-32 influence before applying
the replacement.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from patch_framework import PreimageGuard  # noqa: E402


def parse_offset(value: str) -> int:
    try:
        offset = int(value, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"invalid offset: {value}") from error
    if offset < 0:
        raise argparse.ArgumentTypeError("offset cannot be negative")
    return offset


def parse_hex(value: str) -> bytes:
    try:
        payload = bytes.fromhex(value.replace("_", " "))
    except ValueError as error:
        raise argparse.ArgumentTypeError("replacement must be hexadecimal") from error
    if not payload:
        raise argparse.ArgumentTypeError("replacement cannot be empty")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("rom", type=Path, help="local source ROM")
    parser.add_argument("offset", type=parse_offset, help="ROM offset, such as 0x055CEE")
    parser.add_argument(
        "replacement_hex",
        type=parse_hex,
        help="replacement bytes; their length determines the guarded source range",
    )
    args = parser.parse_args()

    rom = args.rom.read_bytes()
    end = args.offset + len(args.replacement_hex)
    if end > len(rom):
        parser.error(
            f"range {args.offset:#08x}..{end:#08x} exceeds the {len(rom)}-byte ROM"
        )
    guard = PreimageGuard.from_bytes(
        args.offset,
        rom[args.offset:end],
        len(rom),
    )
    print(f"            source_genesis_sum={guard.genesis_sum},")
    print(
        "            source_crc32_influence="
        f"0x{guard.crc32_influence:08X},"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
