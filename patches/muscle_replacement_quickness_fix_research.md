# Muscle Replacement Quickness fix research

This is the static-evidence record for
[`muscle_replacement_quickness_fix.py`](muscle_replacement_quickness_fix.py).
Addresses refer to the canonical 2 MiB headerless US ROM.

## Affected Quickness consumers

Muscle Replacement uses cyberware bits `5..8` in actor word `+$90`. The stock
melee-power loop at `0x055D26` is the authoritative rank decoder: the first
set bit represents levels 1 through 4. Three gameplay consumers instead read
the unmodified base Quickness byte at `+$78`:

| Consumer | Address | Stock operation |
| --- | ---: | --- |
| Action speed and Matrix power | `0x00D81C` | Load Quickness, add Intelligence, and average. |
| Combat Pool | `0x055ED6` | Load Quickness, then add Intelligence and Willpower. |
| Combat movement | `0x00B648` | Load Quickness, clamp to 9, then index the movement table. |

`0x00D81C` is reached by the action-speed scheduler at `0x00D7EA` and by the
Matrix power path. The other two consumers are independent, so all three hooks
are required for the advertised Quickness bonus to affect its gameplay uses.

## Shared Party Quickness in scripted encounters

The dialogue action handler also has a shared party-Quickness helper at
`0x023750`. It sums the raw Quickness byte of every active party member at
`0x02376E`, then divides by the active-member count.

Eight dialogue/event actions call this helper:

| Action | Handler ROM address | Situation | Target number |
|---:|---:|---|---:|
| 153 | `0x023782` | Run from Lone Star | 4 normally, modified by armor |
| 212 | `0x0244D2` | Avoid a hidden security camera | 4, +1 per companion |
| 215 | `0x0245AA` | Jump over a pressure plate | 4, +1 per companion |
| 216 | `0x0245F4` | Stop before breaking laser beams | 8 |
| 219 | `0x02466C` | React before security gets the drop on the party | 8 |
| 220 | `0x0246AA` | Subdue a woman before she raises the alarm | 6 |
| 224 | `0x024846` | Shoot a fleeing Company Man | 7 |
| 238 | `0x024B5A` | Hide from a wilderness encounter | 5, 6, or 8 by encounter |

All eight currently average each active member's **stored/base** Quickness.
Muscle Replacement is ignored.


## Helper contract

The patch's 40-byte helper returns `effectiveQuickness(A0)` in `D1`. It uses
the stock rank-decoding order and preserves `D0`, `D6`, and `D7`, matching the
register contract of each displaced sequence.

Each six-byte `JSR` resumes in the original arithmetic:

1. `0x00D81C` returns to `0x00D822` for the Intelligence add and average.
2. `0x055ED6` returns to `0x055EDC` for Combat Pool arithmetic.
3. `0x00B648` returns to `0x00B64E` for the stock movement cap and lookup.

The six-byte hook at `0x02376E` replaces both `ADD.B $78(A3),D6` and
`ADDQ.B #1,D0`. Its 16-byte adapter uses `EXG A0,A3` around the existing helper
and then reproduces those two instructions using the returned effective
Quickness. It preserves `A0` and `A3` while retaining the stock loop and
division behavior. The helper's eight callers immediately overwrite or ignore
`D1`, so retaining that otherwise preserved register would not affect any
current caller and would waste four bytes of audited tail space.

Movement remains capped at effective Quickness 9 by the original table, while
higher effective Quickness still benefits action speed, Combat Pool, and Matrix
power through their unchanged downstream calculations.
