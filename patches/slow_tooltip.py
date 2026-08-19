"""Update Slow tooltip to explain that it can defeat ICs

Slow has long looked like a junk program: its stock tooltip emphasizes delayed
actions, then bluntly says it does nothing against Trace. In fact it attacks
IC through the same opposed test as Attack, works on Trace & Dump and Trace &
Burn before a trace begins, and can defeat any targetable IC by reducing its
speed far enough. Its unusually large storage size is a clue that it was meant
to be a real alternative, but the interface never teaches that strategy.

What Slow cannot affect is the separate trace process after it has started.
The new tooltip makes that boundary—and Slow's offensive value—discoverable
without requiring players to reverse-engineer the Matrix rules.

Before: The tooltip says that Slow delays attacks and alerts and that it
``does nothing`` against Trace IC

The actual resolver is approximately:

    ic.action_speed -= 2 * net_successes + floor(Slow.rank / 2)
    if ic.action_speed underflows:
        ic.integrity = 0

Patch: Replace the tooltip in place with wording that distinguishes Trace IC
from an active trace and states the defeat behavior. The new encoded text fits
before the next description, so no pointer or renderer changes are needed.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


TOOLTIP = 0x000E3288  # Start of the stock Slow tooltip text


class Patch(PatchSpec):
    id = "slow-tooltip"
    description = (
        "Updated the Slow software tooltip to clarify that Slow can defeat ICs: \"Slows an IC's "
        "attacks and alerts. Does not slow traces. Slowing an IC enough will defeat it.\""
    )
    category = "UI/Display Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Replace the existing tooltip in place with the clarified text.
        builder.replace(
            offset=TOOLTIP,
            source_genesis_sum=1134733,
            source_crc32_influence=0x55FF7123,
            payload=(
                "Slows an IC's attacks and alerts. Does not slow traces.".encode("ascii")
                + b"\x80\x80"  # Encoded-text line controls
                + "Slowing an IC enough will defeat it. ".encode("ascii")
                + b"\xFF"
            ),
        )


PATCH = Patch()
