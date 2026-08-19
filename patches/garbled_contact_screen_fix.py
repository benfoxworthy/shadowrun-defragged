"""Prevent non-contact story flags from exposing the Contacts screen in a garbled state

The longword at ``$FFFC2C`` stores both the thirteen learned-contact bits and
unrelated dialogue-progression flags. Meeting Ratspike for the first time sets
bit 29, even if the player has not learned a contact. The Notebook tested the
entire longword when deciding whether to show Contacts, but the Contacts page
only builds rows from bits 0 through 12. With no learned contacts, its
count-minus-one remains ``$FF``; the drawing loop interprets that as 255 and
reads hundreds of entries beyond the populated pointer list, garbling the
screen.

Before:

    if contact_and_dialogue_flags != 0:
        notebook.add(CONTACTS)

    visible_contacts = contacts_from_bits(contact_and_dialogue_flags, 0, 12)
    last_row = len(visible_contacts) - 1  # no contacts: $FF
    draw_rows_through(last_row)           # DBF draws 256 invalid rows

Patch: Make both Contacts entry checks read only the low word at ``$FFFC2E``.
All thirteen contact bits are in that word, bits 13 through 15 are unused, and
the unrelated progression flags are in the high word. The Notebook therefore
shows Contacts exactly when the renderer has at least one valid row, and the
standalone contact interface retains its intended no-contacts path.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "garbled-contact-screen-fix"
    description = (
        "Fixed the Contacts screen appearing before any contacts were learned and rendering "
        "garbled graphics after meeting a gang boss, such as Ratspike."
    )
    category = "UI/Display Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Preserve the standalone contact interface's no-contacts path when
        # only unrelated progression flags are set in the high word.
        builder.replace(
            offset=0x00E4D6,
            source_genesis_sum=73060,
            source_crc32_influence=0x8C4A93B1,
            payload=bytes.fromhex(
                "303900FFFC2E"  # MOVE.L ($FFFC2C).L,D0 -> MOVE.W ($FFFC2E).L,D0
            ),
        )

        # Add the Notebook's Contacts item only when at least one learned-
        # contact bit is present in the low word.
        builder.replace(
            offset=0x00F38A,
            source_genesis_sum=83940,
            source_crc32_influence=0x700A04A2,
            payload=bytes.fromhex(
                "4A7900FFFC2E"  # TST.L ($FFFC2C).L -> TST.W ($FFFC2E).L
            ),
        )


PATCH = Patch()
