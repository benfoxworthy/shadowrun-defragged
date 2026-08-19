# Compact spell effect-slot leak fix

## Symptom and allocator evidence

The game's eighteen-byte dynamic-effect allocation bitmap is at work RAM
`0xFFD86C..0xFFD87D`. A captured failing battle state had all 18 entries
allocated but no corresponding set of live spell/projectile owners. Once full,
both targeted spells and firearm/thrown projectile construction take their
allocation-failure paths. The persistent “nobody can attack” state is therefore
shared effect-slot exhaustion, not exhaustion of general Genesis RAM.

## Stock ownership failures

`spawn_targeted_spell_effect` at `$015830` allocates a slot and eventually
writes it to target `+$32`, with the spell action in target `+$B2`. It does not
first release an effect already attached to that target. The new spell replaces
the only reference to the old allocation, so the older slot leaks permanently.

An attached spell can also lose its normal completion path if its actor is
deactivated. Invisibility (action 4) and Rockskin (action 11) are immediate
effects, but the shared constructor still allocates a slot which their handlers
never release.

AoE spells add two related ownership errors:

- Hellblast (3), Sleep (5), and Mana Storm (10) release their slot at the end
  of each target leg, yet copy that same numeric slot ID to the next target. A
  different effect can claim the freed bitmap entry before a later leg clears
  it again.
- All five AoE handoff routines overwrite the next actor's `+$B2/+$32` without
  releasing an effect that actor already owns. Stink (6) and Confusion (13)
  retain their allocation through the chain, but still have this collision
  leak.

AoE chaining is implemented by the individual effect handlers and candidate
markers at actor `+$DE`; there is no separate chain object. The sequential
wrappers look for another active, non-bit-6 actor whose marker equals the AoE
action, then transfer the current actor's `+$32` slot to it.

Those distributed markers create a second interruption bug. Stock terminal
cleanup clears the chain's `+$DE` markers across the ten standard actors.
Stink and Confusion additionally clear `+$DF` bits 0 and 1, respectively. If
the chain's sole `+$B2` effect controller is overwritten, no handler remains to
reach that cleanup. Stink or Confusion can consequently leave a real gameplay
penalty active after its visible effect has disappeared.

## Enabled compact design

The enabled patch preserves the stock one-effect-per-target and
newest-effect-wins behavior. It repairs allocation ownership and the logical
AoE state orphaned by the same cancellation events:

1. Before targeted setup allocates, release the target's existing effect and
   clear `+$B2`.
2. After a successful Invisibility or Rockskin setup allocation, release that
   otherwise-unused slot immediately.
3. Before the common initial publication at `$0158E0`, release the actor that
   the AoE candidate builder actually selected. Stink/Confusion's premature
   `+$B2` write at `$015A36` is suppressed so it cannot hide the existing
   effect.
4. At completion of Hellblast, Sleep, or Mana Storm, clear the completed
   actor's action/marker but retain its allocation if the stock target rules
   show that another marked actor remains. Release it only on the final leg.
   Direct Flame Bolt and Mana Blast uses of the shared handlers still release
   immediately.
5. Before every AoE handoff, release the destination actor's existing effect,
   then publish the incoming action. This covers Hellblast, Mana Storm, Sleep,
   Confusion, and Stink.
6. On common actor deactivation, release any still-published attached effect.
7. Whenever an effect is cancelled, remember its old action. If the incoming
   effect has a different action and no other active actor still publishes the
   old action in `+$B2`, clear only matching `+$DE` markers. Also clear the
   corresponding `+$DF` bit across all actors for Stink or Confusion. A
   same-action replacement keeps the shared state for its new controller; if
   its allocation fails, the old action is checked again because no replacement
   controller was created.

The compact implementation adds seven helpers totaling **472 bytes**. It uses
12 fixed-site hooks totaling 118 bytes, but those replace stock bytes and do
not consume code-cave capacity.

## Deliberately preserved stock behavior

To minimize gameplay changes and testing burden, the patch intentionally does
not:

- change damage or healing eligibility for dead/downed/dying actors;
- add completion-time death guards or prevent a spell death animation from
  being restarted;
- validate a new cast before cancelling its existing effect;
- preserve an existing effect when Invisibility or Rockskin is cast;
- reconstruct damage from an effect that stock overlap rules interrupt;
- redesign the shared Stink/Confusion controller state;
- clear the shared Stink/Confusion timers or return-target pointer during
  interruption (they are inert without an owner, while an incoming status AoE
  may already have initialized them);
- make concurrent instances of the same AoE independent (their distributed
  candidate/status state remains intentionally shared);
- change the global allocator reset; or
- queue multiple logical effects per target.

Those behaviors can still cause interrupted casts, truncated AoE chains, or
odd status/death visuals, but the enabled patch ensures the associated live
allocation is released instead of becoming permanently unreachable. The patch
cannot retroactively repair an in-progress battle state in which stock code has
already left an AoE carrying a freed or reassigned numeric slot ID.

## Patch sites

| ROM offset | Compact responsibility |
| --- | --- |
| `$015868` | Targeted release-before-allocation guard and failed-replacement cleanup |
| `$015A36` | Suppress premature status-AoE `+$B2` publication |
| `$0158E0` | Collision-safe common initial publication and orphan cleanup |
| `$005008`, `$005178`, `$005348` | Mana/Hellblast and Flame/Hellblast, plus Sleep completion ownership |
| `$004D14`, `$004D8A`, `$0052F4`, `$005470`, `$00563E` | Five collision-safe AoE handoffs with orphan cleanup |
| `$01E524` | Common actor-deactivation release and orphan cleanup |
