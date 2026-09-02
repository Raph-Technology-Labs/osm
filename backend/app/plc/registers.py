"""Register address constants for the PLC handshake simulator/poller.

Holding registers only. See docs/specs/plc_simulator.md for the register
map this task implements. PULSE_COUNT is a uint32 spanning two consecutive
registers (encoded big-endian: PULSE_COUNT holds the high word,
PULSE_COUNT + 1 the low word) so it can be batch-read together with
HEARTBEAT in a single request.
"""

SPEED_SETPOINT = 0  # PC -> PLC, uint16, RPM x10, written once at session start
PULSE_COUNT = 1  # PLC -> PC, uint32 (addr 1-2), free-running, wraps at encoder_cpr
PULSE_COUNT_WIDTH = 2  # registers
HEARTBEAT = 3  # PLC -> PC, uint16, increments every PLC scan tick, wraps mod 65536
HEARTBEAT_WIDTH = 1  # registers

# PULSE_COUNT and HEARTBEAT are laid out contiguously so a poll can batch-read
# both in one request (Throughput Design Requirement 1) -- derive the count
# from the widths above rather than hand-counting, so a register inserted
# between them can't silently desync this.
POLL_BATCH_WIDTH = PULSE_COUNT_WIDTH + HEARTBEAT_WIDTH
