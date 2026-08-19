"""Use the party's best Computer skill for the 'Hack the database' random event

A random encounter inside a corp run can give an option to hack a database for
information (dialogue action 223). Success reveals which floor the objective is
on, failure can trigger an alarm.

Before:
This action reads only Joshua's Computer skill:

    dice = joshua.computer_skill;
    successes = successTest(dice, targetNumber = 5);

A companion's Computer expertise cannot help, so a Computer 0 Joshua always
sets off the alarm even while an active decker with a high Computer skill is in
the party. The analogous Electronics terminal action already selects the best
skill among active party members.

Patch: Replace Joshua's direct skill check with a active-party maximum helper:

    best = 0;
    for (member in partySlots[0..2]) {
        if (member.active)
            best = max(best, member.computer_skill);
    }
    dice = best;

The existing target number, alarm path, result thresholds, objective-floor
selection, and dialogue text remain unchanged.
"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


class Patch(PatchSpec):
    id = "corp-terminal-computer-skill-fix"
    description = (
        "Use the party's best Computer skill instead of only Joshua's for the "
        "'Hack the database' random event during corp runs."
    )
    category = "Gameplay Bug Fixes"

    def build_patch(self, builder: PatchBuilder) -> None:
        # D6 has already been cleared by the stock CLR.L immediately before
        # this hook. Find the highest Computer skill (+$88) among the three
        # active character records, leaving the result in D6 for the existing
        # TN-5 success test.
        best_active_computer_skill_address = builder.add_cave(
            bytes.fromhex(
                "41F900FF0100"  # LEA active_character_data,A0
                "7E02"          # MOVEQ #2,D7 (three party slots)
                "082800000010"  # loop: BTST #0,$10(A0) (active)
                "670A"          # BEQ.S next_member
                "10280088"      # MOVE.B $88(A0),D0 (Computer)
                "B006"          # CMP.B D6,D0
                "6B02"          # BMI.S next_member (skill < best)
                "1C00"          # MOVE.B D0,D6 (skill >= best)
                "41E80100"      # next_member: LEA $100(A0),A0
                "51CFFFE8"      # DBF D7,loop
                "4E75"          # RTS
            )
        )

        # Keep the stock CLR.L D6 at $0247D0 and resume at its existing
        # target-number load after the helper returns.
        builder.replace(
            offset=0x0247D2,
            source_genesis_sum=7872,
            source_crc32_influence=0x4C8566CD,
            payload=bytes.fromhex(
                "4EB9"  # JSR absolute-long best_active_computer_skill
                f"{best_active_computer_skill_address}"
            ),
        )


PATCH = Patch()
