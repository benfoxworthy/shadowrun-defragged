# Cyberdeck storage upgrades research

This is the long-form design and implementation record for
[`cyberdeck_storage_upgrades.py`](cyberdeck_storage_upgrades.py).

## Motivation

The immediate motivation is [`tar_pit_rework.py`](tar_pit_rework.py). Once Tar
Pit stops permanently deleting software, the player has no way to remove an
owned program. Filling a small deck with undesirable programs can leave too
little room for the software the player actually wants and can be a "stuck"
state with no resolution.

Adding a delete command would require new interface, confirmation, and text
work, and would create its own risk of accidental loss. Expanding the existing
storage-upgrade system solves the capacity problem through a mechanic the game
already teaches.

## Stock behavior

The stock purchase check is approximately:

```text
if deck.totalStorage >= deck.MPCP * 80:
    report_maximum()
else:
    charge_flat_price()
    deck.totalStorage += 25
```

The comparison uses TOTAL storage, not storage purchased above the model's
base. As a result, a deck with generous factory storage can begin above its
upgrade ceiling, making it so no upgrades are possible. It's not clear if this
is intended behavior.

| Model | MPCP | Stock base MP | Stock `MPCP * 80` cap | Purchases possible |
| --- | ---: | ---: | ---: | ---: |
| Starter deck | 3 | 100 | 240 | 6, ending at 250 |
| Cyber Shack PCD-500 | 4 | 100 | 320 | 9, ending at 325 |
| Fuchi Cyber-5 | 6 | 500 | 480 | 0 |
| SEGA CTY-360 | 8 | 500 | 640 | 6, ending at 650 |
| Fuchi Cyber-7 | 10 | 1,000 | 800 | 0 |
| Fairlight Excalibur | 12 | 1,000 | 960 | 0 |

The 80-MP cap interval and 25-MP upgrade interval are incommensurate. Because
the game checks before purchasing, a deck may legally overshoot the nominal cap
slightly. Three of the five models cannot upgrade at all.

## Selected design

The new rule measures purchased storage relative to the deck model's base:

```text
rank = truncate_toward_zero((currentStorage - modelBaseStorage) / 50)
maximumRank = deck.MPCP * 2

if rank >= maximumRank:
    report_maximum()

price = max(200, 200 + 150 * rank)
storageAdded = 50
```

This gives every model a predictable number of upgrades while allowing higher
quality decks to grow further.

The Fairlight Excalibur also had its base storage increased slightly from
1,000 MP to 1,250 MP. This is so that at least one deck can hold every program
at max rank, with room for data files.

| Model | MPCP | Patched base MP | Max ranks | Maximum MP | Total upgrade cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| Starter deck | 3 | 100 | 6 | 400 | 3,450¥ |
| Cyber Shack PCD-500 | 4 | 100 | 8 | 500 | 5,800¥ |
| Fuchi Cyber-5 | 6 | 500 | 12 | 1,100 | 12,300¥ |
| SEGA CTY-360 | 8 | 500 | 16 | 1,300 | 21,200¥ |
| Fuchi Cyber-7 | 10 | 1,000 | 20 | 2,000 | 32,500¥ |
| Fairlight Excalibur | 12 | 1,250 | 24 | 2,450 | 46,200¥ |

The first rank costs 200¥. Each later rank costs 150¥ more, so the 24th and
last Excalibur purchase costs 3,650¥. Storage remains easy to start expanding
but becomes a meaningful long-term expense.

## Why 50 MP

Twenty-five MP gives fine-grained control but makes a fully expanded Excalibur
require forty-eight purchases under the new capacity goal. Fifty MP cuts that
to twenty-four clicks and makes each purchase visible without turning storage
into a single all-or-nothing upgrade.

## Collection ceiling

Every obtainable program at maximum rank occupies 2,108 MP. A deck can also
hold at most five datafiles, and the largest datafile is 60 MP, so the absolute
worst-case datafile load is 300 MP. A fully upgraded 2,450-MP Excalibur can
therefore hold the entire max-rank program library plus five maximum-size
datafiles—2,408 MP total—with 42 MP spare.

This is intentionally an endgame completionist ceiling, not the expected
capacity of an ordinary playthrough.

## Runtime memory remains unchanged

The separate runtime-memory upgrade uses a similar stock check:

```text
if deck.totalMemory >= deck.MPCP * 40:
    report_maximum()
else:
    deck.totalMemory += 10
```

| Model | MPCP | Base memory | Nominal cap |
| --- | ---: | ---: | ---: |
| Starter deck | 3 | 30 | 120 |
| Cyber Shack PCD-500 | 4 | 50 | 160 |
| Fuchi Cyber-5 | 6 | 100 | 240 |
| SEGA CTY-360 | 8 | 200 | 320 |
| Fuchi Cyber-7 | 10 | 300 | 400 |
| Fairlight Excalibur | 12 | 500 | 480 |

Its 10-MP increments divide evenly into the cap, and the Excalibur's base-over-
cap anomaly merely prevents further upgrades to an already generous active
loadout. Unlike storage, runtime memory does not create a permanent clogged-
deck state. No gameplay need to redesign it has been identified, so this patch
deliberately leaves it alone.

## Save compatibility

Existing saves require two accommodations:

- A legacy deck can be 25 MP off the new 50-MP grid. Its next purchase adds
  25 MP to complete the half-step; later purchases add 50.
- An old Excalibur may contain 1,000 MP while the new model base is 1,250.
  Signed rank calculation and a zero price floor let it buy upgrades normally
  rather than treating the save as corrupt or already maximized.

The starter deck's old sentinel model ID is normalized to model 0. Sentinel
records mirror the Cyber-7 and Excalibur base values so the compact helper can
use one linear five-model lookup across the stock split table.

## Implementation boundaries

The patch replaces the stock cap/price calculation but returns to the original
affordability and confirmation flow. Body, Persona, and Response upgrades keep
their original behavior. Only the Storage branch changes its increment.

Useful runtime checks include buying every rank on each model, reopening the
shop at the maximum, testing insufficient funds, loading legacy half-step and
1,000-MP Excalibur saves, and verifying program/datafile capacity accounting.
