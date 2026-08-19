"""Stop one crashed CPU from unlocking every Maglock for the rest of the game.

``Crash System`` sets two temporary physical-security flags: one suppresses
alarms and cameras, while the other makes Maglock collision checks succeed.
The physical-map loader reset the first flag but forgot the second. As a
result, crashing any CPU anywhere could make every subsequent Maglock behave
as if it were unlocked—an enormous permanent exploit hidden behind an ordinary
Matrix action.

Before:

    crash_system():
        suppress_security_callbacks = true
        bypass_maglocks = true

    load_physical_map():
        suppress_security_callbacks = false
        # bypass_maglocks was never cleared

Patch: Encode two nearby RAM clears in their shorter equivalent form, making
room for a third clear of ``bypass_maglocks`` without a hook or code cave. It
runs at every true physical-map load. Elevator floor changes use a lighter
transition and do not clear it, so crashing a building's CPU still helps for
the rest of that run; leaving for another map ends the exploit.

The focused state-lifetime audit is in
``crashed_cpu_transition_fix_research.md`` beside this module.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "crashed-cpu-transition-fix"
    description = (
        "Fixed the \"crashed CPU\" flag never being cleared on map transitions. Crashing a CPU in "
        "the Matrix now disables Maglock doors only when done inside a corp building during a "
        "run."
    )
    category = "Gameplay Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Clear the crashed-CPU Maglock bypass with the existing security state.
        # Absolute-word RAM addresses sign-extend, fitting three clears in the
        # same twelve bytes previously occupied by two absolute-long clears.
        builder.replace(
            offset=0x0167D2,
            source_genesis_sum=149839,
            source_crc32_influence=0xD7261AE2,
            payload=bytes.fromhex(
                "4238E16F"  # CLR.B ($E16F).W -> $FFE16F
                "4238E170"  # CLR.B ($E170).W -> $FFE170
                "4238E17F"  # CLR.B ($E17F).W -> $FFE17F
            ),
        )


PATCH = Patch()
