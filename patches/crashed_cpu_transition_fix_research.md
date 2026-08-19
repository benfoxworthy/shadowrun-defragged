# Crashed CPU transition fix: state-lifetime audit

This is the focused static-evidence record for
[`crashed_cpu_transition_fix.py`](crashed_cpu_transition_fix.py). All
addresses refer to the canonical headerless US ROM
(`SHA-1 A06A281D39E845BFF446A541B2FF48E1D93143C2`).

## Verified state lifecycle

The Matrix `Crash System` action at `0x054B34` sets two transient
physical-security bytes together:

- `$FFE170` suppresses corporate-map timed callbacks and random security
  events.
- `$FFE17F` bypasses Maglock collision handling; it also resolves an already
  queued Maglock interaction.

The physical-map loader (`0x0167AE`) clears `$FFE170` at `0x0167D8`, but the
base game does not clear `$FFE17F`. No other direct gameplay clear of
`$FFE17F` exists. This lets the Maglock bypass survive into a later map.

## Repair and regression boundary

The patch preserves the two adjacent stock clears and uses their shorter,
sign-extending absolute-word encoding to add the missing reset in the same
twelve bytes:

```asm
CLR.B ($E16F).W    ; stock clear of $FFE16F
CLR.B ($E170).W    ; stock clear of $FFE170
CLR.B ($E17F).W    ; new clear of $FFE17F
```

It changes no general register, adds no helper or code-cave allocation, and
leaves the next stock instruction at `0x0167DE` intact. The bypass remains
available for the current physical-map run and resets at the same lifecycle
boundary as the existing security state.

## Evidence locations

| Behavior | Location |
| --- | --- |
| Crash System writes both bytes | `0x054B6E` and `0x054B76` |
| `$FFE170` callback consumers | `0x0163E6` and `0x01DFD8` |
| `$FFE17F` Maglock consumer | `0x020E50` |
| Physical-map reset sequence | `0x0167D2..0x0167DE` |
