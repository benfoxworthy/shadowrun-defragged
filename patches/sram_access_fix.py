"""Fix saving on certain physical cartridges that require the SRAM-access flag
to be set during save and load.

Genesis games typically keep saved games in battery-backed SRAM (or FRAM) built
into the cartridge. The RAM shares the cartridge address range with ROM, so a
cartridge can require the game to write to the SRAM-access control register at
``$A130F1`` to toggle between ROM and SRAM memory at ``$200000``. Writing
``$01`` selects the SRAM window and allows reads and writes.

Shadowrun reads and writes its saves at the normal address, but its original
save/load routines assume that SRAM is already selected at that range. That
was likely a safe assumption for its original cartridge, whose hardware likely
always enabled SRAM (Shadowrun is a 2MB cartridge, so its ROM data does not
conflict with the SRAM addresses). However, some third-party flashable
cartridges require the SRAM-enable flag to be set (for example, the EPICJOY
MD Flashmaster 4MB + 32k FRAM). This causes Shadowrun saves and loads to fail
on those cartridges.

This patch writes the SRAM-access control flag immediately before every
Shadowrun save/load. It leaves the game's save address, layout, block sizes,
redundancy, and checksum rules unchanged, so existing saves remain compatible.
This should have no effect in emulators or hardware that already worked, while
fixing save/load for hardware that does require the flag.

Note: This patch does not clear the SRAM-access flag after reading/writing.
This is not an issue because the Shadowrun ROM is only 2MB and never reads that
space, but this patch would need improvement if Shadowrun Defragged ever
expands the ROM past 2MB.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


SAVE_READ = 0x000014CE
SAVE_WRITE = 0x000014E8
SRAM_CONTROL = 0x00A130F1


class Patch(PatchSpec):
    id = "sram-access-fix"
    description = (
        "Fixes saving/loading on certain physical cartridges that require the "
        "Genesis SRAM-access flag to be set during save and load."
    )
    category = "Compatibility"

    def build_patch(self, builder: PatchBuilder) -> None:
        read_helper = builder.add_cave(
            bytes.fromhex(
                f"13FC0001{SRAM_CONTROL:08X}"  # MOVE.B #1,$A130F1
                "207C00200000"  # MOVEA.L #$200000,A0: displaced stock op
                f"4EF9{SAVE_READ + 6:08X}"  # JMP stock reader after its setup
            )
        )
        write_helper = builder.add_cave(
            bytes.fromhex(
                f"13FC0001{SRAM_CONTROL:08X}"  # MOVE.B #1,$A130F1
                "207C00200000"  # MOVEA.L #$200000,A0: displaced stock op
                f"4EF9{SAVE_WRITE + 6:08X}"  # JMP stock writer after its setup
            )
        )

        builder.replace(
            offset=SAVE_READ,
            source_genesis_sum=8348,
            source_crc32_influence=0x763FD0BC,
            payload=bytes.fromhex(f"4EF9{read_helper:08X}"),
        )
        builder.replace(
            offset=SAVE_WRITE,
            source_genesis_sum=8348,
            source_crc32_influence=0x69D76911,
            payload=bytes.fromhex(f"4EF9{write_helper:08X}"),
        )


PATCH = Patch()
