---
name: modbus-register-design
description: Use this skill whenever adding, renaming, or reviewing a PC-PLC Modbus TCP register in this project. Covers naming conventions, CMD/ACK pairing rules, direction/ownership, and the escalation logic for missed acknowledgments. Trigger on any mention of a register name, REJECT_CMD, OK_CMD, HEARTBEAT, or Modbus register.
---

# Modbus Register Design

## Ownership rule

Whoever *writes* a register owns it. The other side only ever reads it.
`PLC → PC` always means the PC reads; `PC → PLC` always means the PC writes.
Never have both sides write the same register.

## CMD means command

A `_CMD` register (always `PC → PLC`, always Write) is an instruction to
physically act — not a status report. Every `_CMD` must have a matching `_ACK`
register (always `PLC → PC`, always Read) confirming the PLC actually carried
it out. Never treat "command sent" as equivalent to "command executed" — that
gap is exactly where a NOK part can silently escape.

## Naming pattern

- `<ACTION>_CMD` / `<ACTION>_ACK` — paired instruction/confirmation
- `<ACTION>_CMD_<n>` / `<ACTION>_ACK_<n>` — when there are multiple instances
  of the same action (e.g. multiple in-line reject stations), number them and
  keep the numbering contiguous with the number of configured stations of that
  type
- Plain status registers (`PART_SENSOR`, `PULSE_COUNT`, `HEARTBEAT_PLC`) don't
  need CMD/ACK — they're continuous state, not one-shot instructions

## The two reject topologies — same pattern either way

- **Scenario A (in-line, segregated by station):** one `REJECT_CMD_<n>` /
  `REJECT_ACK_<n>` pair per reject station.
- **Scenario B (single final bin):** exactly one `REJECT_CMD_1` /
  `REJECT_ACK_1` pair, evaluated after all camera stations have reported.

`OK_CMD` / `OK_ACK` is always exactly **one** pair regardless of which
scenario — only one exit point, only one "part cleared" signal.

## Missed-ACK escalation is NOT uniform severity

- Missed `REJECT_ACK` within timeout → `FAULT_STATUS = 1` **and**
  `STOP_COMMAND = 1`. A NOK part may have physically escaped — this is a
  safety/containment issue, not just an operational one.
- Missed `OK_ACK` within timeout → `FAULT_STATUS = 1` only. Likely a jam or
  stuck part, not a containment failure — don't halt the line automatically
  for this without a stated reason.

Don't write one shared "any missed ACK stops the machine" handler — the two
cases have different real-world consequences and should stay distinguishable
in code, not just in a comment.

## Before adding any new register

1. Check the register list documentation for the next free address in the
   right block (control registers vs. status registers are usually kept in
   separate address ranges — follow whatever convention the existing list
   uses).
2. Confirm the direction and R/W with whoever owns the PLC program — a
   register direction mismatch between the PC's assumption and the actual TIA
   Portal program is a hardware-safety issue, not a typo.
3. Update the register list doc in the same change that adds the register to
   code. A register that exists in code but not in the doc is a debugging trap
   for the next person.
