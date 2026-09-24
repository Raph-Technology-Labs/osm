# Dispatcher has no tick source: PLC offline at backend startup

- **Date seen:** 2026-09-24
- **Area:** PLC / session start (`app/inspection_session.py`, `load_machine`)
- **Severity:** High: session could not start
- **Status:** Worked around (PLC reconnected, backend restarted). Code follow-up open.
- **Fix commit(s):** none yet

## Summary
While the 192.168.7.x switch was being replaced, the backend started with the
network down, so its one PLC connection attempt failed. The backend kept
running without a PLC client. Session start then failed because, in real mode,
the dispatcher has nothing to drive its ticks.

## Symptom
```
StationDispatcher has no tick source: plc.sim.enabled is False but no
plc_client was given to drive real-hardware polling. Set plc.sim.enabled=True
to run the dispatcher's own timer tick, or pass a connected ModbusPLCClient
for real-PLC dispatch.
```

## Diagnosis
1. `cat /sys/class/net/enp4s0/operstate` returned `down`, speed `-1`, and no
   IPv4 address: the PC wasn't connected to the new switch yet.
2. After re-cabling, the link was up at 1000 Mbit/s, but
   `ping 192.168.7.72` got no reply ("+2 errors" = no ARP reply).
3. `ip neigh show dev enp4s0` showed `192.168.7.41 REACHABLE` (camera) and
   `192.168.7.72 INCOMPLETE` (PLC). The camera was on the new switch; the PLC
   wasn't.
4. `inspection_session.py:78-99`: `load_machine()` connects to the PLC **once,
   at backend startup**. If that fails, it sets `app.state.plc_client = None`
   and never retries.

## Root cause
Two things combined:
- **Physical:** the PLC was not plugged into the new switch after the swap.
- **Software:** the PLC connection is only tried at startup, with no retry at
  session start. So even after the PLC came back, the running backend could
  not use it until restarted, and the error message didn't say the PLC was
  the problem.

## Actions taken
- PLC cable moved to the new switch, then the backend was restarted. The next
  session ran with real-PLC dispatch (encoder ticks visible in the log).

## Prevention
- **Checklist:** after any network change on 192.168.7.x, confirm the PLC
  (.72) and controller (.71) show up in `ip neigh show dev enp4s0` before
  starting the backend.

## Follow-ups
- **Recommended code change (not done):** at session start, if
  `app.state.plc_client is None` and `plc.sim.enabled` is false, retry
  `connect()` + `read_heartbeat()` once. If that still fails, return a clear
  400 such as "PLC at 192.168.7.72:502 not reachable". That removes the need
  for a backend restart and makes the error point at the real problem.
