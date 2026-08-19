# Tar Pit rework research

This is the long-form companion to
[`tar_pit_rework.py`](tar_pit_rework.py). It records the temporary-disable
design, its lifecycle, and the otherwise non-obvious UI and RAM decisions.

## Design goal

Stock Tar Pit permanently clears the rating of the affected owned program.
The player loses every purchased rank without confirmation or recovery.

The rework keeps the threat strategically meaningful for the current Matrix
run:

```text
stock:
    ownedProgramRank[programID] = 0
    unloadProgram()

patched:
    tarredProgramMask |= 1 << programID
    unloadProgram()
    rejectReloadsWhileMarked()
    clearAllMarksWhenJackingOut()
```

Tar Paper remains the lighter effect: it performs the stock unload but does
not set the temporary-disable mask.

## Why the mask uses program IDs

The cyberdeck owns twelve program types but loads only five programs at once.
A mask keyed by active slots would lose the identity of a victim as soon as
the player filled its vacated slot.

The patch uses one bit per program ID:

```text
bit 0  -> program ID 0
...
bit 11 -> program ID 11
```

This allows several different programs to remain disabled simultaneously while
the five active slots are reused.

## RAM selection

The mask occupies word `$FFE0FE`. The static audit found:

- no direct reference to that word in the generated disassembly or reference
  reports;
- direct word users immediately before it at `$FFE0FC` and after it at
  `$FFE100`, with no access spanning the gap;
- no base-pointer access covering the neighborhood;
- the only indexed `$FFE0xx` scratch table ends below `$FFE04A`.

That is sufficient static evidence for an aligned session word, but a runtime
watchpoint remains the best final check for an unrelated dynamic writer.

## Marking and unloading

At the stock Tar Pit effect site, `D0` still contains the affected program ID.
The replacement helper sets the corresponding mask bit and restores the Tar
Pit animation subtype expected by later code.

The stock animation-midpoint callback remains intact. It calls the ordinary
cyberdeck unload routine, which removes the program from an active slot, clears
its active state, and redraws combat UI. Ownership/rank is never modified.

## Blocking reloads

The cyberdeck load path already computes the selected program ID and rejects
programs the player does not own. The patch replaces that ownership test with:

```text
if ownedProgramRank[selectedProgram] == 0:
    rejectLoad()
if tarredProgramMask has bit selectedProgram:
    rejectLoad()
continueWithStockSlotAndCapacityChecks()
```

Untarred programs therefore use every original installed-slot and storage rule.

## Cyberdeck-grid overlay

A disabled program must be visible before the player tries to load it. The
start-menu grid contains twelve cells in four columns and three rows. The
overlay helper consumes the mask in the same order and appends the existing
Tar animation Frame 02 over each marked icon.

The Matrix-combat Tar sprite normally uses palette line 1, but the cyberdeck
menu replaces that palette with bright interface colors. The helper installs
the original dark Tar colors into unused entries of palette line 0 and draws
the overlay there. The menu's normal exit path reloads the target-dependent
palette block, so those temporary colors do not leak into Matrix combat.

The cursor is appended first and retains its stock palette.

## Session lifetime

The outer Matrix session owns a combat loop. Moving between Cyber Combat
encounters returns to that loop; closing and reopening the cyberdeck menu does
not end it. Only the final jack-out teardown leaves the session.

The mask clear is hooked into that one final teardown:

```text
between encounters: preserve tarredProgramMask
menu close/open:     preserve tarredProgramMask
final Matrix exit:   tarredProgramMask = 0
```

The helper then tail-calls the displaced stock cleanup routine.

## Interaction with storage upgrades

Once programs are no longer permanently deleted, there is no in-game way to
remove obsolete owned software. That motivated
[`cyberdeck_storage_upgrades.py`](cyberdeck_storage_upgrades.py), which makes
capacity expansion available on every deck. The patches are conceptually
paired but remain independently selectable.
