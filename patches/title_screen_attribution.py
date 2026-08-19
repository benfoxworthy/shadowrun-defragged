"""Render a manifest-specific Shadowrun Defragged attribution on the title screen."""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


TITLE_SCREEN_LAST_COPYRIGHT_DRAW = 0x001E44
TITLE_SCREEN_ATTRIBUTION_VDP_ADDRESS = 0x0000CD84
TITLE_SCREEN_PALETTE_3_FONT_INK = 0x002066
TITLE_SCREEN_TEXT_COLUMNS = 40
TITLE_SCREEN_TEXT_LEFT_MARGIN = 2
TITLE_SCREEN_MAXIMUM_VISIBLE_CHARACTERS = 36
# The shared font uses color index 11.  Palette 3 is title-screen local.
ORANGE_FONT_PALETTE = 0x6000
BANNER_ORANGE_CRAM = 0x004A


class Patch(PatchSpec):
    id = "title-screen-attribution"
    description = (
        "Adds the manifest display name and version below the title-screen "
        "(c) 1994 SEGA attribution."
    )
    category = "Attribution/Diagnostics"

    def __init__(self, display_text: str = "Shadowrun Defragged v1.0") -> None:
        self.display_text = display_text

    def with_display_text(self, display_text: str) -> "Patch":
        """Return this patch configured with one manifest's release label."""

        if (
            not display_text.isascii()
            or not display_text.isprintable()
            or not display_text
            or len(display_text) > TITLE_SCREEN_MAXIMUM_VISIBLE_CHARACTERS
        ):
            raise ValueError("invalid title-screen attribution text")
        return type(self)(display_text)

    def build_patch(self, builder: PatchBuilder) -> None:
        # The stock screen draws the Sega copyright at $CC84.  Its final jump
        # becomes a cave routine which finishes that draw and writes the
        # manifest label at $CD84, one complete row below the old $CD04 spot.
        padding = (
            (TITLE_SCREEN_TEXT_COLUMNS - len(self.display_text)) // 2
            - TITLE_SCREEN_TEXT_LEFT_MARGIN
        )
        encoded_text = b" " * padding + self.display_text.encode("ascii") + b"\xFF"
        text_address = builder.add_cave(encoded_text)
        routine_address = builder.add_cave(self._routine_payload(text_address))
        builder.replace(
            offset=TITLE_SCREEN_LAST_COPYRIGHT_DRAW,
            source_genesis_sum=41269,
            source_crc32_influence=0xA03A73AC,
            payload=bytes.fromhex(f"4EF9{routine_address:08X}"),
        )
        builder.replace(
            offset=TITLE_SCREEN_PALETTE_3_FONT_INK,
            source_genesis_sum=70,
            source_crc32_influence=0x55ED8315,
            payload=BANNER_ORANGE_CRAM.to_bytes(2, "big"),
        )

    @staticmethod
    def _routine_payload(text_address: int) -> bytes:
        """Return the text-rendering trampoline plus its in-cave text."""

        return (
            bytes.fromhex(
                "4EB90000C0DA"
                f"247C{TITLE_SCREEN_ATTRIBUTION_VDP_ADDRESS:08X}"
                f"43F9{text_address:08X}"
                f"323C{ORANGE_FONT_PALETTE:04X}"
                "4EB90000C0DA"
                "4E75"
            )
        )


PATCH = Patch()
