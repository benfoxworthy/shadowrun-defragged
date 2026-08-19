"""Fix Thon becoming stuck with no valid attacks after only nine spell casts.

Thon's repeated Flame Darts were observed to stop during long fights. The spell
record correctly says zero drain, but the shared NPC resolver “helpfully”
forces any nonpositive value to one. Thon loses a mental box per cast until he
no longer has a legal action, and then does nothing, waiting for death  — a sad
failure mode for the final boss.

Before:

    drain = selected_spell.drain  # Flame Dart: 0
    if npc_caster and drain <= 0:
        drain = 1
    caster.mental_health -= drain

Patch: Preserve zero instead of forcing one. Positive-drain enemy spells branch
around this instruction and behave exactly as before; Hell Hound fire breath
uses a separate drain-free special path.

Research Notes:
The selected spell record supplies its drain at `+$24`. Flame Dart supplies
zero, but the NPC-only branch at `0x055BE0` replaces nonpositive drain with
one before the unchanged subtraction at `0x055BE8`. The length-preserving
replacement clears `D6` instead.

Among known enemy templates, only Thon uses a zero-drain record; Corp Mage and
Gator Shaman use Flame Bolt (drain 1), Rat Shaman uses Sleep (2), and Elven
Mage uses Mana Blast (1). Hell Hound fire breath uses a custom hard-coded
attack that never enters this record-drain path.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "thon-no-spell-drain"
    description = (
        "Thon no longer suffers drain from his spell and can cast it indefinitely, preventing "
        "him from getting stuck with no valid attacks after casting nine times during the final "
        "battle."
    )
    category = "Gameplay Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Preserve a zero spell-record drain instead of forcing it to one.
        # D6 already contains the selected spell's drain; positive values
        # bypass this block and remain unchanged.
        builder.replace(
            offset=0x055BE4,
            source_genesis_sum=15421,
            source_crc32_influence=0x868AC0AF,
            payload=bytes.fromhex(
                "4246"  # CLR.W D6
                "4E71"  # NOP (length-preserving replacement)
            ),
        )


PATCH = Patch()
