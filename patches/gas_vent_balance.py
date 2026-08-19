"""Make Gas Vents less powerful to rebalance SMGs

The attachment bug effectively crippled SMGs because they have a built-in
"recoil penalty" of TN +3 (a huge penalty), which is supposed to be mitigated
by Gas Vents. Once repaired, (see 'firearm_attachment_slot_fix'), SMGs with a
Gas Vent are extremely strong due to having comparable accuracy to a Pistol but
with three separate attacks per burst. This meant that a fully-modded HK could
kill most enemies reliably in a single burst even at a firearms skill of only
around 6.

This patch rebalances SMGs to make them less overwhelming compared to other
weapons by reducing the effectiveness of Gas Vents so that they can't fully
negate the recoil penalty. This makes SMGs slightly less accurate than Pistols
and Shotguns, which partly offsets the advantage of having three attacks:

Before:
Gas Vent II reduced TN by 2.
Gas Vent III reduced TN by 3 (fully negating the recoil penalty).

    tn = 4;
    if (isSMG(weapon)) {
        tn += 3;
        if (flags & GAS_VENT_II) tn -= 2;
        else if (flags & GAS_VENT_III) tn -= 3;
    }
    // ... Laser Sight, Smartlink, wounds, status, and vision modifiers
    tn = max(2, tn);

Patch:
Gas Vent II reduces TN by 1.
Gas Vent III reduces TN by 2 for the first round, and 1 for the second/third.

Additionally, the order of operations is swapped so that weapon recoil is
applied last, AFTER the clamp to a minimum TN 2. This means that the minimum TN
for an SMG burst is 3/4/4 even with both a Smartlink and Cyber Eyes.

    tn = 4;
    // ... Laser Sight, Smartlink, wounds, status, and vision modifiers
    tn = max(2, tn);
    if (isSMG(weapon)) {
        tn += 3;
        GAS_VENT_III_MODS = [-2, -1, -1];
        if (flags & GAS_VENT_III) tn += GAS_VENT_III_MODS[shotIdx];
        else if (flags & GAS_VENT_II) tn -=1;
    }

Note: This patch reads the Gas Vent attachment slots from the equipped weapon
slot directly and does not depend on the broader firearm-attachment fix.

"""

from __future__ import annotations

from patch_framework import PatchBuilder, PatchSpec


# Gas Vent TN modifiers for each shot in the three-round burst.
GAS_VENT_III_MODS = (-2, -1, -1)
GAS_VENT_II_MODS = (-1, -1, -1)


class Patch(PatchSpec):
    id = "gas-vent-balance"
    description = (
        "Reduce effectiveness of Gas Vents. Gas Vent II now reduces TN by 1 "
        "instead of by 2, and Gas Vent III now reduces TN by 2/1/1 (based on "
        "which round in the burst) instead of by 3. Also swaps order of "
        "operations so that the minimum TN of 2 is applied BEFORE recoil."
    )
    category = "Balance Improvements"

    def build_patch(self, builder: PatchBuilder) -> None:
        if len(GAS_VENT_III_MODS) != 3 or len(GAS_VENT_II_MODS) != 3:
            raise ValueError("Gas Vent modifiers must contain exactly three shots")

        # Each configurable modifier occupies one two-byte instruction, keeping
        # the branch layout below fixed. Zero is represented by a NOP.
        modifier_opcodes = {
            0: "4E71",   # NOP
            -1: "5344",  # SUBQ.W #1,D4
            -2: "5544",  # SUBQ.W #2,D4
            -3: "5744",  # SUBQ.W #3,D4
        }
        try:
            gas_vent_iii_first = modifier_opcodes[GAS_VENT_III_MODS[0]]
            gas_vent_iii_second = modifier_opcodes[GAS_VENT_III_MODS[1]]
            gas_vent_iii_third = modifier_opcodes[GAS_VENT_III_MODS[2]]
            gas_vent_ii_first = modifier_opcodes[GAS_VENT_II_MODS[0]]
            gas_vent_ii_second = modifier_opcodes[GAS_VENT_II_MODS[1]]
            gas_vent_ii_third = modifier_opcodes[GAS_VENT_II_MODS[2]]
        except KeyError as error:
            raise ValueError(
                "Gas Vent modifiers must be 0, -1, -2, or -3"
            ) from error

        # Remove the stock pre-clamp SMG arithmetic. Laser Sight, Smartlink,
        # visibility, and wounds still resolve before the stock TN-2 clamp.
        builder.replace(
            offset=0x0556DC,
            source_genesis_sum=22084,
            source_crc32_influence=0x817F5B2E,
            payload=bytes.fromhex("4E71"),  # ADDQ.W #3,D4 -> NOP
        )
        builder.replace(
            offset=0x0556EA,
            source_genesis_sum=21828,
            source_crc32_influence=0x09C87E62,
            payload=bytes.fromhex("4E71"),  # SUBQ.W #2,D4 -> NOP
        )
        builder.replace(
            offset=0x0556FA,
            source_genesis_sum=22340,
            source_crc32_influence=0xA200B29F,
            payload=bytes.fromhex("4E71"),  # SUBQ.W #3,D4 -> NOP
        )

        # A1 is the current projectile. Its +$8B burst byte separates the first
        # shot from later shots. For later shots, +$41 is one on the second shot
        # and zero on the third. Apply recoil and the selected per-shot vent
        # modifier, then tail-jump to the displaced roll so its RTS returns to
        # the original firearm caller at $0556AA.
        post_clamp_recoil = builder.add_cave(
            bytes.fromhex(
                "0C2800080057"      # CMPI.B #8,$57(A0): below SMG IDs?
                "6B000068"          # BMI.W roll
                "0C28000B0057"      # CMPI.B #11,$57(A0): above SMG IDs?
                "6A00005E"          # BPL.W roll
                "5644"              # ADDQ.W #3,D4: post-clamp recoil
                "4280"              # CLR.L D0
                "10280056"          # MOVE.B $56(A0),D0: equipped slot
                "08300005006E"      # BTST #5,($6E,A0,D0.W): Gas Vent III
                "67000024"          # BEQ.W check Gas Vent II
                "4A29008B"          # TST.B $8B(A1): first burst shot?
                "67000010"          # BEQ.W Gas Vent III first modifier
                "4A290041"          # TST.B $41(A1): second burst shot?
                "6600000E"          # BNE.W Gas Vent III second modifier
                f"{gas_vent_iii_third}"
                "60000036"          # BRA.W roll
                f"{gas_vent_iii_first}"
                "60000030"          # BRA.W roll
                f"{gas_vent_iii_second}"
                "6000002A"          # BRA.W roll
                "08300004006E"      # BTST #4,($6E,A0,D0.W): Gas Vent II
                "67000020"          # BEQ.W roll
                "4A29008B"          # TST.B $8B(A1): first burst shot?
                "67000010"          # BEQ.W Gas Vent II first modifier
                "4A290041"          # TST.B $41(A1): second burst shot?
                "6600000E"          # BNE.W Gas Vent II second modifier
                f"{gas_vent_ii_third}"
                "6000000A"          # BRA.W roll
                f"{gas_vent_ii_first}"
                "60000004"          # BRA.W roll
                f"{gas_vent_ii_second}"
                "4EF900000DBA"      # roll: JMP dice success test
            )
        )
        builder.replace(
            offset=0x0556A4,
            source_genesis_sum=23667,
            source_crc32_influence=0xE66E1B3B,
            payload=bytes.fromhex(f"4EB9{post_clamp_recoil:08X}"),
        )


PATCH = Patch()
