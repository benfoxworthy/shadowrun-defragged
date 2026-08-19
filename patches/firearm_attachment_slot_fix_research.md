# Firearm attachment slot fix research

This is the long-form companion to
[`firearm_attachment_slot_fix.py`](firearm_attachment_slot_fix.py). It records
the player-facing symptoms, the combat-formula context, and the static argument
for the repair. Offsets refer to the canonical 2 MiB headerless US ROM.

## Why this bug matters

This single bug explains two of the game's strangest weapon-balance observations:

- Shotguns can appear to gain Smartlink accuracy without a Smartgun System.
- The HK227-S looks excellent on paper but often performs much worse than its
  attachments imply.

SMGs fire three projectiles. Each projectile makes a separate attack roll and
receives the stock +3 burst target-number penalty. Gas Vents are supposed to
offset that penalty, so failing to read them makes all three shots substantially
less accurate. Conversely, a phantom Smartgun flag lowers a shotgun's target
number even though shotguns cannot accept that attachment.

The original discovery was described for players in the GameFAQs post
[New findings from reverse-engineering combat formulas](https://gamefaqs.gamespot.com/boards/366854-shadowrun/81169515).

## The stock lookup

The relevant portion of the firearm target-number calculation is:

```text
slot = actor.equippedWeaponSlot
weaponID = actor.equippedWeaponID

targetNumber = baseRangeTargetNumber

if weaponID is an SMG:
    targetNumber += 3

flags = actor.attachmentFlags[weaponID - 1]  // BUG

if flags has GasVentII:
    targetNumber -= 2
if flags has GasVentIII:
    targetNumber -= 3
if flags has LaserSight:
    targetNumber -= 1
if flags has SmartgunSystem:
    targetNumber -= 2 when actor has Smartlink
    targetNumber -= 1 when actor has Smart Goggles
```

The eight inventory item IDs live at actor offsets `+$66..+$6D`. The eight
attachment bytes live at `+$6E..+$75`, in the same slot order. The equipped
weapon slot is stored at `+$56`; the equipped weapon's item ID is at `+$57`.

The stock routine loads `+$57`, subtracts one, and uses that value to index
`+$6E`. It is confusing an item-type ID with an inventory-slot index.

## What the bad index reads

For weapon IDs 1-8, the lookup stays within the attachment array but works only
when the weapon happens to occupy slot `weaponID - 1`.

Higher weapon IDs read the actor fields immediately following the array:

| Weapon | Item ID | Field mistaken for attachment flags |
| --- | ---: | --- |
| HK227-S | 9 | Equipped armor ID (`+$76`) |
| Mach 22 | 10 | Body (`+$77`) |
| Allegiance | 11 | Quickness (`+$78`) |
| Roomsweeper | 12 | Strength (`+$79`) |

This is why the bug can manufacture plausible-looking attachment effects. Bit
0 represents Smartgun System, so any odd armor ID or attribute looks like a
Smartgun. Values 8-15 have the Laser Sight bit set.

The HK227-S and Mach 22 are hurt most. Armor IDs top out below the Gas Vent II
bit, and normal Body values cannot reach the Gas Vent II/III bits either. Their
real Gas Vents are ignored while the full +3 SMG penalty remains. Depending on
the phantom flags, the HK can be four target-number points less accurate than
a correctly upgraded pistol or shotgun.

## Why `+$56` is the right replacement

The active firearm mode at actor `+$56` is the actual inventory slot, not just
a menu cursor. The shared firearm-launch sequence already uses it to read the
same attachment array for Silencer and Sound Suppressor. Every normal player,
party, and NPC firearm shot goes through that launch path.

Using the slot directly is also better than searching inventory for the weapon
ID. A character may own two copies of the same gun with different attachments;
an item search would always choose one copy, while the equipped-slot field
identifies the one actually fired.

Silencers and Sound Suppressors are not part of the broken accuracy helper and
must remain unchanged.

The slot is retained in `D0` through all four accuracy checks. The only caller
of this helper is `roll_firearm_attack`, which immediately calls `0x000D5A`
and overwrites `D0`; returning the slot rather than the former item-derived
index cannot affect later behavior.

### Gas Vent upgrade state

Testing this patch revealed a secondary bug:

Gas Vent II and III use separate attachment bits. The weapon can retain both
bits after a player upgrades an SMG. The stock code tests Gas Vent II first,
so if both bits are set, the game incorrectly uses the weaker modifier.

The repair consumes the bits in the opposite priority: III, then II. A small
code-cave selector reads the already-corrected slot index in `D0` and jumps to
the original subtraction instruction for the selected vent. This deliberately
leaves those instructions in place. The independent `gas-vent-balance` patch
performs its own slot lookup and III-before-II priority check, NOPs the stock
pre-clamp arithmetic, and applies its configurable compensation after the TN-2
clamp. Because priority is resolved at use time, no save-file migration is
needed.

## In-place repair

The patch keeps the equipped slot in `D0` for all four attachment tests. The
two SMG-range comparisons are changed to read the weapon ID directly from
actor `+$57`, and a redundant later weapon-ID reload is removed.

| Offset | Original | Replacement purpose |
| --- | --- | --- |
| `0x0556C8` | load `+$57` | load slot from `+$56` |
| `0x0556CC` | compare `D0` with IDs 8 and 11 | compare `+$57` directly; retain slot |
| `0x0556FC` | reload/decrement weapon ID | NOPs; retain slot for Laser/Smartgun |

The Gas Vent priority repair uses a small code-cave selector. The helper's
caller immediately invokes a routine that overwrites `D0`, so retaining the
slot index does not change later behavior.

## Enemy loadout impact

Enemies use the same eight inventory slots, attachment bytes, and shared
firearm accuracy routine as the player and party. The repair therefore restores
the accessories authored into their templates as well. Three loadouts become
meaningfully more accurate:

| Enemy template | Weapon and real equipment | Stock lookup | Fixed result |
| --- | --- | --- | --- |
| Strike Team | AK-97 with Gas Vent II, Smartgun System, and Sound Suppressor | Empty attachment slot; no accuracy benefit | Gas Vent II removes `2` points of the burst TN penalty |
| Strike Team (other variant) | Max-Power with Smartgun System and Smartlink | Wrong attachment slot | Smartgun/Smartlink grants `-2 TN` |
| Elven Guard | Mach 22 with Smartgun System and Smartlink | Body byte, which lacks the Smartgun bit | Smartgun/Smartlink grants `-2 TN` |

The AK user lacks Smartlink, so its real Smartgun System does not add accuracy.
Its Sound Suppressor already works in the stock game because the separate
noise/alarm routine uses the correct slot.

Not every armed enemy changes. The Prison Guard's Allegiance has a real
Smartgun System and Smart Goggles, but the broken lookup reads its Quickness.
That value happens to contain the same Smartgun bit, reproducing the intended
`-1 TN`; the repair changes the source of the bonus, not its size. Other
gun-using templates either lack a relevant attachment or the equipment needed
to use it.
