"""Fix Tar Pit/Paper applying instantly after Shops or certain dialogues

A scratch byte is shared by several otherwise unrelated systems: A failed
Rebound uses it as a flag for the Matrix to trigger Tar Pit/Paper, but shops,
dialogue, and character screens can also leave it nonzero. Matrix startup
forgot to clear it. This meant that mundane UI activity could - apparently
randomly - cause the next encountered Tar Pit or Tar Paper to trigger
instantly, even on a successful attack roll.

Before:

    if rebound_failure_latch:
        run_tar_failure_path()
    # Matrix initialization did not reset the latch

Patch: Re-encode two existing session-state clears in shorter forms, fitting a
third clear of the Rebound latch into the same twelve bytes. A real Rebound
failure can still set it later in the session and follows the stock Tar path.

Research notes:

`$FFF0B6` is the Rebound-failure override consumed by the generic Matrix
program launcher. The failed-Rebound handler deliberately writes `0xFF` at
`0x01B8DC`. Matrix-session initialization begins at `0x01ADE6` and clears
many session-state fields, but its stock clears at `0x01ADFA` omit this byte.
Dialogue, shop, and character-screen paths can also leave the shared scratch
byte nonzero, so a stale value crosses the Matrix-session boundary.

The replacement preserves the stock clears of `$FFDF8C` and `$FFE080` and
adds a clear of `$FFF0B6`. On the 68000, the absolute-word addresses
`$DF8C.W`, `$E080.W`, and `$F0B6.W` sign-extend to those work-RAM addresses,
so the three four-byte instructions replace the two six-byte absolute-long
instructions without changing registers or control flow. The next stock
instruction at `0x01AE06` remains intact. `0x01745E` is the sole direct caller
of the initializer, making it the right Matrix-session lifecycle boundary:
stale UI state is removed while a real failed Rebound can still set the latch
later in the same session.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "tar-pit-premature-activation-fix"
    description = (
        "Fixed entering shops or certain dialogues causing Tar Pit or Tar Paper to activate "
        "instantly when next encountered."
    )
    category = "Gameplay Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # Clear the stale Rebound latch alongside the existing session state.
        # Absolute-word RAM addresses sign-extend, fitting three clears in the
        # same twelve bytes previously occupied by two absolute-long clears.
        builder.replace(
            offset=0x01ADFA,
            source_genesis_sum=149244,
            source_crc32_influence=0x8B8ED32E,
            payload=bytes.fromhex(
                "4278DF8C"  # CLR.W ($DF8C).W -> $FFDF8C
                "4278E080"  # CLR.W ($E080).W -> $FFE080
                "4238F0B6"  # CLR.B ($F0B6).W -> $FFF0B6
            ),
        )


PATCH = Patch()
