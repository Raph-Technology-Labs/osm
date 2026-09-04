"""Register address constants for the PLC handshake simulator/poller.

Per the instrumentation team's register sheet. Numbers are literal Modicon
4xxxx addresses, exactly as given -- NOT 0-based pymodbus protocol
addresses. pymodbus's read/write calls want a 0-based address, so the 40001
offset must be subtracted at the point of use wherever these are actually
issued in a request.

Only PULSE_COUNT, HEARTBEAT, and SPEED_SETPOINT are wired into poller.py's
control flow today. The rest are named constants only -- using them in the
actual poll/control loop is separate poll-loop design work
(docs/spec03_polling_threads.md), not resolved here.
"""

PULSE_COUNT = 40001              # PLC->PC, int -- "Encoder actual pulse"
ENCODER_INDEXER_PPR = 40002      # PLC->PC, int -- "Reset to 0 at Indexer Revolution"
ENCODER_COUNT = 40003            # PLC->PC, long -- "Total pulses from machine start to stop"
PART_SENSOR = 40004              # PLC->PC, bool -- "part detection at entry"
HEARTBEAT = 40005                # PLC->PC -- per-slot heartbeat tick count (1,2,3...)
INDEXING_PULSE = 40006           # PLC->PC, bool -- "0,1 after sending reset bit"
HEARTBEAT_PER_SLOT = 40007       # PC->PLC, int -- PC-configured heartbeat cadence, in pulses
INDEXING_PULSE_PER_SLOT = 40008  # PC->PLC, int -- PC-configured pulses-per-slot
REJECT_CMD = 40009               # PC->PLC, bool -- rejected-part command
STOP_CMD = 40010                 # PC->PLC, bool -- halt execution
SPEED_SETPOINT = 40011           # PC->PLC, int, 0-1000 scale, written once at session start
FAULT = 40012                    # BOTH sides R/W per the sheet -- register-ownership-rule
                                  # conflict, modeled as given (see machine_config.yaml comment)
