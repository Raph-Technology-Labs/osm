# PLC link drop stopped the dispatcher for good (no reconnect)

- **Date seen:** 2026-09-28 18:24
- **Area:** Dispatcher / Modbus client / session start
- **Severity:** High: machine silently stops dispatching (UI still "RUNNING") until the backend is restarted
- **Status:** Fixed in code. Hardware re-test pending.
- **Fix commit(s):** see the commit that adds this report

## Summary
A Modbus connection failure raised `ConnectionException` inside the
dispatcher's tick. Nothing caught it, so the `threading.Timer` tick thread
died, no further tick was scheduled, and dispatch stopped permanently with no
reconnect. The PLC then also refused new connections until it was restarted,
and the backend could only reconnect by being restarted as well: it only
connects to the PLC at startup.

## Symptom
```
18:24:23 dispatcher: Dispatcher started ...  /motor/start 200 OK
18:24:26 [ERROR] pymodbus.logging: Connection to (192.168.7.72, 502) failed: timed out
Exception in thread Thread-730:
  File "app/indexer/dispatcher.py", line 398, in _tick_real
    pulse_sensor_batch = self.plc_client.read_registers(
pymodbus.exceptions.ConnectionException: Modbus Error: [Connection] Failed to connect
```
After a backend restart: `PLC connect failed during machine load -- continuing without it.`

## Diagnosis
- `ping 192.168.7.72` answered (0.3 ms) and ARP showed REACHABLE, but a raw
  TCP connect to **port 502 got no answer**. The PLC was up, but its Modbus
  server wasn't accepting.
- No process on this PC held a connection to `192.168.7.72:502`.
- The PLC is a Raspberry Pi-based controller (MAC `d8:3a:dd:…`) whose Modbus
  server accepts **one** client at a time. A second client (monitor/tester)
  times out, and a connection that died without closing can keep the slot
  busy.
- Code:
  - `ModbusPLCClient.read_registers()` only handled error responses
    (`rr.isError()`). pymodbus *raises* on a dead link, so the exception
    escaped unwrapped and `is_connected()` stayed True: no UI toast.
  - `_tick_real()` schedules the next tick only at its end, so an exception
    ends the chain.
  - `load_machine()` is the only place that connects.

## Root cause
No error boundary around the real-mode tick, pymodbus exceptions not
normalized in the client, and a connect-once-at-boot design. The PLC's
single-connection Modbus server made a drop likely: two readers at once, a
stale slot, or a runtime hang.

## Actions taken
- `ModbusPLCClient`: every request wraps `ModbusException`/`OSError` into
  `PLCConnectionError` and marks the client disconnected, so health and the
  ConnectionAlerts toast report the outage. New `reconnect()` closes the stale
  socket and opens a fresh one.
- `StationDispatcher._tick_real_guarded()` (real-mode tick entry):
  - on `PLCConnectionError` it logs once, **reconnects with backoff**
    (0.5 s doubling to 5 s) and keeps scheduling; nothing is dispatched
    while down;
  - any other exception is logged with a traceback and the next tick runs
    normally. The tick chain can't die any more.
- **On recovery:** if the outage × pre-outage speed ≥ half a revolution, the
  unwrap can't know where the disc went. The dispatcher logs an ERROR and
  publishes `plc_outage` on RingState. The Inspection page shows **"Disc
  tracking lost — restart the session"**. Shorter outages keep tracking and
  log a warning.
- `inspection_session._connect_plc()`: one helper for machine load **and**
  session start. If the PLC wasn't reachable at boot, session start tries
  again, so a PLC restart no longer needs a backend restart.

- **Tuned after the first cable-pull test (18:42):** pymodbus defaults
  (`timeout=3 s`, `retries=3`) made a dead link hang a read ~9 s before
  failing, and each reconnect attempt take 3 s. They're now config:
  `plc.modbus_timeout_s: 1.0`, `plc.modbus_retries: 1` (a healthy read is
  ~1 ms), so a drop is detected in ~1-2 s. The outage log is time-based: one
  line on the first failure, then "PLC still unreachable at ip:port (N
  attempts, down X s)" every 10 s, instead of attempts 1/5/20 (which looked
  stuck).

## Prevention
- Tests:
  - `tests/test_modbus_client_errors.py` (4, incl. configured timeout/retries): raised exceptions become
    `PLCConnectionError` and mark disconnected; `reconnect()` closes the stale
    socket.
  - `tests/test_dispatcher_real_mode.py` (4): the chain survives with backoff
    0.5 → 1 → … → 5 s; recovery resumes dispatch and keeps tracking after a
    short outage; a long outage at speed flags tracking as unreliable; a
    non-PLC tick error is logged and dispatch continues; the outage log appears at t=0/10/20 s, not on every attempt.
- **Operating rule:** the PLC accepts ONE Modbus client. Run
  `plc_monitor.py` / `modbus_tester.py` only with the backend stopped.

## Follow-ups
- If the PLC's Modbus server keeps hanging, ask the PLC programmer about its
  connection limit and idle timeout, so a dead client's slot is freed
  automatically.
- Consider stopping the session automatically (not just alarming) when
  tracking is flagged unreliable.
