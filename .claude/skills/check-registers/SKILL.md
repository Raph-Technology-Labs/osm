---
name: check-registers
description: Audit that every PLC register referenced in code has a matching, consistent entry in the register list doc and follows CMD/ACK pairing rules
disable-model-invocation: true
---

Cross-check the project's register usage for consistency. Specifically:

1. Find every register name referenced in `app/plc/modbus_client.py` (or wherever
   the Modbus client lives) and in any YAML config/recipe files.

2. Compare against the register list documentation. Flag:
   - any register used in code but not documented
   - any register documented but never referenced in code (may be dead, or the
     code hasn't caught up — ask which, don't assume)
   - any direction mismatch (a register the code writes that's documented as
     PLC→PC, or vice versa)

3. Check CMD/ACK pairing: every register ending in `_CMD` should have a
   corresponding `_ACK` register, and both should appear together everywhere
   they're used (a `_CMD` written without its `_ACK` ever being read is a bug).

4. Check that `REJECT_CMD_<n>` / `REJECT_ACK_<n>` numbering is contiguous and
   matches the number of configured reject stations in the current recipe files
   — a mismatch here usually means a station was added or removed without
   updating the register wiring.

5. Confirm `PULSE_COUNT` is never used with a raw division for slot-boundary
   detection anywhere in the codebase — it should only ever flow through the
   wrap-corrected accumulator in the tracker.

Report findings as a table: register name, where documented, where used in code,
issue found (or "OK"). Don't fix anything automatically — this is an audit, ask
before making changes.
