"""
Slot Calculator — Modbus TCP motor start/stop/log console.

Same Flask + pymodbus shape as app/plc/tester.py: Start / Stop the motor,
show live pulses, log a reading on demand. Register numbers are literal
Modicon 4xxxx numbers per app/plc/registers.py / machine_config.yaml
(source of truth) — holding registers only, no coils:

  part_sensor          (40004, bool, r) -- "part detection at entry". Rising
                                            edge (0->1) is this tool's zero
                                            point: SLOT_PULSE_COUNT resets to
                                            0 the instant the sensor trips,
                                            per explicit instruction
                                            (2026-09-12) so pulses can be
                                            counted per-part instead of
                                            per-revolution.
  encoder_indexer_ppr  (40002, int, r)  -- "reset to 0 at Indexer Revolution"
                                            per the sheet. Raw source for
                                            SLOT_PULSE_COUNT, per explicit
                                            instruction (switched from
                                            encoder_count/40003 -- see below).
  encoder_count         (40003, long, r) -- kept and shown as a raw reference
                                            reading only, NOT used for the
                                            slot math below any more. Live
                                            hardware readings (2026-09-12,
                                            this tool) show it as a huge
                                            (~10-digit) monotonically
                                            increasing value that does not
                                            reset at encoder_cpr, contradicting
                                            machine_config.yaml's "CONFIRMED
                                            2026-09-12" note that it resets
                                            once per revolution -- that
                                            register's real behavior is still
                                            unsettled (see that file's own
                                            "operator is re-checking this
                                            register live" comment). Flag with
                                            the instrumentation team before
                                            trusting either register's
                                            documented reset behavior blindly.
  stop_cmd              (40010, bool, rw) -- Start writes 1 (run), Stop
                                            writes 0 (halt) -- combined
                                            run/stop per explicit operator
                                            instruction (2026-09-07), not the
                                            sheet's original pure-halt-bit
                                            meaning.
  speed_setpoint        (40011, int, rw)  -- written once when Start is
                                            pressed, 0-1000 scale per the
                                            sheet (rpm-to-0-1000 conversion is
                                            UNCONFIRMED -- the typed value is
                                            sent as-is, no scaling applied).

SLOT_PULSE_COUNT (the "since presence sensor" relative pulse count) is
computed with the exact same never-trust-a-single-raw-read wrap-correction
pattern as app/indexer/tracker.py's IndexerSlotTracker.on_pulse_update() /
the indexer-ring-math skill: never divide/compare raw register values
directly across a reset, always accumulate a wrap-corrected gap. The
accumulator resets on the sensor's rising edge (software-side, entirely
under this tool's control) -- it does NOT depend on the PLC ever resetting
encoder_indexer_ppr itself. The gap-correction wrap boundary is
REGISTER_WRAP (65536, the register's actual 16-bit hardware range), NOT
ENCODER_CPR (4800) -- live testing (2026-09-12) showed motor stop/restart
does not zero the raw register (expected: stop/start has no effect on an
encoder register at all, it only freezes/resumes wherever the disc
physically is), and encoder_indexer_ppr's "resets to 0 at Indexer
Revolution" sheet label was already flagged in app/plc/registers.py as
untested against real hardware -- same unconfirmed-label problem
encoder_count/40003 turned out to have (see below). Using 4800 as the wrap
boundary here would have been trusting that same kind of unconfirmed claim;
65536 is a certainty of the register's bit width, not a claim from the
sheet, so slot_pulse_count stays correct whether or not the PLC ever
actually performs a revolution-based reset. ENCODER_CPR is kept only as a
display reference (the "/ 4800" progress figure in the UI) -- to actually
confirm real pulses-per-revolution, watch slot_pulse_count itself across
two consecutive presence-sensor triggers rather than trusting either raw
register's documented reset behavior. A background poll thread (poll_loop)
does this at a fixed cadence independent of the UI's refresh rate, same
shape as app/plc/poller.py -- so no sensor edge is missed between browser
polls.

Dev tool, not for production PLCs -- same caveat as tester.py.
pip install flask pymodbus
"""

import struct
import threading
import time
from flask import Flask, request, jsonify, render_template_string
from pymodbus.client import ModbusTcpClient

app = Flask(__name__)

MODBUS_ADDRESS_OFFSET = 40001  # config/registers.py store the literal 4xxxx number; pymodbus wants 0-based

PART_SENSOR_ADDR = 40004 - MODBUS_ADDRESS_OFFSET          # 3, bool
ENCODER_INDEXER_PPR_ADDR = 40002 - MODBUS_ADDRESS_OFFSET  # 1, int -- slot-count raw source
ENCODER_COUNT_ADDR = 40003 - MODBUS_ADDRESS_OFFSET        # 2, long -- raw reference only
STOP_CMD_ADDR = 40010 - MODBUS_ADDRESS_OFFSET              # 9, bool -- 1=run, 0=halt
SPEED_SETPOINT_ADDR = 40011 - MODBUS_ADDRESS_OFFSET        # 10, int, 0-1000 scale

ENCODER_CPR = 4800  # CONFIRMED (machine_config.yaml, instrumentation team, 2026-09-08) -- one full indexer
                     # revolution. Display reference ONLY (the "/ 4800" progress figure) -- NOT used as the
                     # wrap-correction boundary, see module docstring.
REGISTER_WRAP = 65536  # encoder_indexer_ppr is a single 16-bit holding register -- this is its real,
                        # guaranteed hardware rollover point, used for wrap-correction instead of ENCODER_CPR

DEFAULT_IP = "192.168.7.72"  # per machine_config.yaml plc.ip
DEFAULT_PORT = 502

POLL_INTERVAL_S = 0.05  # PLACEHOLDER -- same order of magnitude as machine_config.yaml's real_poll_interval_ms

STATE = {
    "client": None,
    "lock": threading.Lock(),
    "poll_thread": None,
    "poll_stop": threading.Event(),
    # slot-pulse tracking (see module docstring)
    "sensor_last": None,          # last part_sensor bool read, None until the first successful poll
    "last_indexer_raw": None,     # last encoder_indexer_ppr raw value, for wrap-corrected delta
    "slot_pulse_count": 0,        # accumulator, reset on every part_sensor rising edge
    # last-known-good readout, served to the UI without issuing a fresh Modbus round trip
    "status": {"part_sensor": None, "encoder_indexer_ppr": None, "encoder_count": None, "slot_pulse_count": 0},
}


def get_client() -> ModbusTcpClient:
    if STATE["client"] is None:
        raise RuntimeError("Not connected")
    return STATE["client"]


def decode_long(regs):
    # 2 x 16-bit holding regs -> unsigned 32-bit int (big-endian word order)
    packed = struct.pack(">HH", regs[0], regs[1])
    return struct.unpack(">I", packed)[0]


def poll_loop(stop_event: threading.Event) -> None:
    """Background thread: reads part_sensor + encoder_indexer_ppr (+ the
    encoder_count reference) at a fixed cadence and maintains
    slot_pulse_count, independent of how often the browser polls /api/status.
    Continuous polling (not once-per-UI-request, as the original /api/pulse
    read was) is what makes rising-edge detection reliable -- a sensor pulse
    that comes and goes between two 1s UI polls would otherwise be missed
    entirely. Mirrors app/plc/poller.py's shape, kept self-contained here
    rather than imported, same standalone-dev-tool choice tester.py made."""
    while not stop_event.is_set():
        with STATE["lock"]:
            client = STATE["client"]
            if client is not None:
                try:
                    rr_sensor = client.read_holding_registers(PART_SENSOR_ADDR, count=1)
                    rr_indexer = client.read_holding_registers(ENCODER_INDEXER_PPR_ADDR, count=1)
                    rr_count = client.read_holding_registers(ENCODER_COUNT_ADDR, count=2)
                    if not rr_sensor.isError() and not rr_indexer.isError() and not rr_count.isError():
                        sensor = bool(rr_sensor.registers[0])
                        indexer_raw = rr_indexer.registers[0]
                        encoder_count = decode_long(rr_count.registers)

                        edge = STATE["sensor_last"] is False and sensor is True
                        STATE["sensor_last"] = sensor

                        if edge:
                            STATE["slot_pulse_count"] = 0
                            STATE["last_indexer_raw"] = indexer_raw
                        elif STATE["last_indexer_raw"] is None:
                            # first successful poll since (re)connect -- just establish the
                            # baseline, no delta to add yet
                            STATE["last_indexer_raw"] = indexer_raw
                        else:
                            last = STATE["last_indexer_raw"]
                            if indexer_raw < last:
                                gap = (REGISTER_WRAP - last) + indexer_raw
                            else:
                                gap = indexer_raw - last
                            STATE["slot_pulse_count"] += gap
                            STATE["last_indexer_raw"] = indexer_raw

                        STATE["status"] = {
                            "part_sensor": sensor,
                            "encoder_indexer_ppr": indexer_raw,
                            "encoder_count": encoder_count,
                            "slot_pulse_count": STATE["slot_pulse_count"],
                        }
                except Exception:
                    pass  # transient read error -- keep last-known-good status, retry next tick
        stop_event.wait(POLL_INTERVAL_S)


def ensure_poll_thread() -> None:
    if STATE["poll_thread"] is None or not STATE["poll_thread"].is_alive():
        STATE["poll_stop"].clear()
        t = threading.Thread(target=poll_loop, args=(STATE["poll_stop"],), daemon=True)
        STATE["poll_thread"] = t
        t.start()


@app.route("/")
def index():
    return render_template_string(PAGE, default_ip=DEFAULT_IP, default_port=DEFAULT_PORT, encoder_cpr=ENCODER_CPR)


@app.route("/api/connect", methods=["POST"])
def connect():
    data = request.get_json()
    ip = data["ip"]
    port = int(data["port"])
    with STATE["lock"]:
        if STATE["client"]:
            STATE["client"].close()
        client = ModbusTcpClient(ip, port=port)
        if not client.connect():
            return jsonify({"ok": False, "error": "connection failed"}), 400
        STATE["client"] = client
        # fresh connection -- slot-pulse tracking starts over, not carried across links
        STATE["sensor_last"] = None
        STATE["last_indexer_raw"] = None
        STATE["slot_pulse_count"] = 0
    ensure_poll_thread()
    return jsonify({"ok": True})


@app.route("/api/status", methods=["GET"])
def status():
    # Serves the background poll thread's last-known-good reading -- no
    # Modbus round trip on this request path, so the UI can poll this as
    # often as it likes without adding PLC traffic.
    with STATE["lock"]:
        return jsonify({"ok": True, **STATE["status"]})


@app.route("/api/start", methods=["POST"])
def start():
    data = request.get_json()
    try:
        speed = int(data["speed"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid speed"}), 400

    with STATE["lock"]:
        try:
            client = get_client()
            rr = client.write_register(SPEED_SETPOINT_ADDR, speed)
            if rr.isError():
                return jsonify({"ok": False, "error": str(rr)}), 400
            rr = client.write_register(STOP_CMD_ADDR, 1)
            if rr.isError():
                return jsonify({"ok": False, "error": str(rr)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def stop():
    with STATE["lock"]:
        try:
            client = get_client()
            rr = client.write_register(STOP_CMD_ADDR, 0)
            if rr.isError():
                return jsonify({"ok": False, "error": str(rr)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True})


PAGE = """
<!doctype html>
<html>
<head>
<title>SLOT CALCULATOR :: START / STOP / LOG</title>
<style>
  :root, html[data-theme="dark"] {
    --bg-gradient: radial-gradient(circle at top left, #0d1420 0%, #05070c 100%);
    --panel: #10151f;
    --border: #1f2b3a;
    --accent: #00e5a0;
    --accent-dim: #00e5a033;
    --danger: #ff4d5e;
    --danger-dim: rgba(255,77,94,0.1);
    --text: #c9d6e3;
    --text-dim: #5c7086;
    --input-bg: #060a10;
    color-scheme: dark;
  }
  html[data-theme="light"] {
    --bg-gradient: radial-gradient(circle at top left, #eef2f7 0%, #ffffff 100%);
    --panel: #ffffff;
    --border: #d7dee6;
    --accent: #0a8f6b;
    --accent-dim: #0a8f6b22;
    --danger: #c62839;
    --danger-dim: rgba(198,40,57,0.08);
    --text: #1b2733;
    --text-dim: #5c6b7a;
    --input-bg: #f5f7fa;
    color-scheme: light;
  }
  * { box-sizing: border-box; }
  body {
    font-family: "JetBrains Mono", "Fira Code", ui-monospace, "Courier New", monospace;
    background: var(--bg-gradient);
    color: var(--text);
    padding: 28px;
    margin: 0;
    min-height: 100vh;
    transition: background 0.2s, color 0.2s;
  }
  h2 {
    margin: 0 0 4px 0;
    letter-spacing: 3px;
    font-size: 20px;
    color: var(--accent);
    text-shadow: 0 0 12px var(--accent-dim);
  }
  h2::before { content: "> "; }
  .top-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .subtitle { color: var(--text-dim); font-size: 12px; margin-bottom: 20px; letter-spacing: 1px; }
  h3 {
    color: var(--text-dim);
    font-size: 12px;
    letter-spacing: 2px;
    text-transform: uppercase;
    margin: 24px 0 10px 0;
    border-bottom: 1px solid var(--border);
    padding-bottom: 6px;
  }
  .panel {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 16px;
    box-shadow: 0 0 24px rgba(0,0,0,0.15);
  }
  .conn-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .label {
    font-size: 11px;
    color: var(--text-dim);
    letter-spacing: 1px;
    text-transform: uppercase;
  }
  input[type=text], input[type=number] {
    background: var(--input-bg);
    border: 1px solid var(--border);
    color: var(--accent);
    padding: 8px 10px;
    border-radius: 3px;
    font-family: inherit;
    font-size: 13px;
    outline: none;
  }
  input[type=text]:focus, input[type=number]:focus {
    border-color: var(--accent);
    box-shadow: 0 0 8px var(--accent-dim);
  }
  button {
    background: transparent;
    color: var(--accent);
    padding: 10px 20px;
    border-radius: 3px;
    border: 1px solid var(--accent);
    cursor: pointer;
    font-family: inherit;
    font-size: 13px;
    letter-spacing: 1px;
    text-transform: uppercase;
    transition: background 0.15s, box-shadow 0.15s;
  }
  button:hover:not(:disabled) { background: var(--accent-dim); box-shadow: 0 0 10px var(--accent-dim); }
  button:disabled { opacity: 0.3; cursor: not-allowed; }
  button.danger { color: var(--danger); border-color: var(--danger); }
  button.danger:hover:not(:disabled) { background: var(--danger-dim); box-shadow: 0 0 10px var(--danger-dim); }
  #theme-toggle {
    color: var(--text-dim);
    border-color: var(--border);
    white-space: nowrap;
    padding: 8px 16px;
    font-size: 12px;
  }
  #theme-toggle:hover { background: var(--accent-dim); border-color: var(--accent); color: var(--accent); }
  #status-dot {
    width: 9px; height: 9px; border-radius: 50%;
    background: var(--danger);
    box-shadow: 0 0 8px var(--danger);
    display: inline-block;
    margin-right: 6px;
  }
  #status-dot.live { background: var(--accent); box-shadow: 0 0 8px var(--accent); }
  .status-text { font-size: 11px; color: var(--text-dim); letter-spacing: 1px; }

  .control-row { display: flex; align-items: center; gap: 24px; flex-wrap: wrap; }
  .control-group { display: flex; flex-direction: column; gap: 6px; }
  .btn-group { display: flex; gap: 10px; }

  .pulse-display {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 28px;
    position: relative;
  }
  .pulse-value {
    font-size: 48px;
    font-weight: bold;
    color: var(--accent);
    text-shadow: 0 0 20px var(--accent-dim);
    letter-spacing: 2px;
  }
  .pulse-label { color: var(--text-dim); font-size: 11px; letter-spacing: 2px; text-transform: uppercase; margin-top: 6px; }
  .pulse-of { color: var(--text-dim); font-size: 13px; margin-left: 6px; }

  .sensor-badge {
    position: absolute;
    top: 14px;
    right: 14px;
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 10px;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--text-dim);
  }
  .sensor-dot {
    width: 10px; height: 10px; border-radius: 50%;
    background: var(--danger); box-shadow: 0 0 8px var(--danger);
  }
  .sensor-dot.on { background: var(--accent); box-shadow: 0 0 8px var(--accent); }

  .stat-row { display: flex; gap: 14px; flex-wrap: wrap; }
  .stat-tile {
    flex: 1 1 200px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 12px 14px;
    border: 1px solid var(--border);
    border-radius: 3px;
    background: var(--panel);
  }
  .stat-tile .stat-label { color: var(--text-dim); font-size: 10px; letter-spacing: 1px; text-transform: uppercase; }
  .stat-tile .stat-value { color: var(--accent); font-size: 20px; font-weight: bold; }

  .log-list { display: flex; flex-direction: column; gap: 6px; max-height: 340px; overflow-y: auto; }
  .log-entry {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    padding: 8px 12px;
    border: 1px solid var(--border);
    border-radius: 3px;
    font-size: 13px;
  }
  .log-entry .key { color: var(--text-dim); }
  .log-entry .val-group { display: flex; align-items: baseline; gap: 10px; }
  .log-entry .val { color: var(--accent); font-weight: bold; }
  .log-entry .val-sub { color: var(--text-dim); font-size: 11px; }
  .log-empty { color: var(--text-dim); font-size: 12px; padding: 8px 2px; }

  #toasts {
    position: fixed;
    bottom: 20px;
    right: 20px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    z-index: 999;
  }
  .toast {
    min-width: 260px;
    max-width: 420px;
    padding: 12px 14px;
    border-radius: 4px;
    font-size: 12px;
    line-height: 1.5;
    background: var(--panel);
    border: 1px solid var(--danger);
    box-shadow: 0 4px 20px rgba(0,0,0,0.3), 0 0 10px var(--danger-dim);
    animation: toast-in 0.15s ease-out;
  }
  .toast.ok { border-color: var(--accent); box-shadow: 0 4px 20px rgba(0,0,0,0.3), 0 0 10px var(--accent-dim); }
  .toast .head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-weight: bold;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--danger);
    margin-bottom: 4px;
  }
  .toast.ok .head { color: var(--accent); }
  .toast .body { color: var(--text-dim); word-break: break-word; }
  @keyframes toast-in {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
  }
</style>
</head>
<body>
  <div class="top-row">
    <div>
      <h2>Slot Calculator</h2>
      <div class="subtitle">TCP // OSM PC&lt;-&gt;PLC start/stop/log console — dev tool, not for production PLCs</div>
    </div>
    <button id="theme-toggle" onclick="toggleTheme()">☀ light</button>
  </div>

  <div class="panel conn-row">
    <span id="status-dot"></span>
    <span class="status-text" id="status-text">disconnected</span>
    <div class="label">ip</div>
    <input id="ip" type="text" value="{{ default_ip }}">
    <div class="label">port</div>
    <input id="port" type="text" value="{{ default_port }}">
    <button onclick="connect()">Connect</button>
  </div>

  <h3>Control</h3>
  <div class="panel control-row">
    <div class="control-group">
      <div class="label">speed setpoint (0-1000)</div>
      <input id="speed" type="number" min="0" max="1000" value="0" style="width:120px">
    </div>
    <div class="btn-group">
      <button id="btn-start" onclick="startMotor()" disabled>Start</button>
      <button id="btn-stop" class="danger" onclick="stopMotor()" disabled>Stop</button>
      <button id="btn-log" onclick="logPulse()" disabled>Log</button>
    </div>
  </div>

  <h3>Slot Pulse Count — resets on presence sensor (#40004)</h3>
  <div class="panel pulse-display">
    <div class="sensor-badge"><span class="sensor-dot" id="sensor-dot"></span><span id="sensor-text">sensor off</span></div>
    <div class="pulse-value" id="pulse-value">--<span class="pulse-of">/ {{ encoder_cpr }}</span></div>
    <div class="pulse-label">slot_pulse_count — since last sensor trigger, from encoder_indexer_ppr (#40002)</div>
  </div>

  <div class="stat-row">
    <div class="stat-tile">
      <div class="stat-label">encoder_indexer_ppr — raw #40002</div>
      <div class="stat-value" id="raw-indexer">--</div>
    </div>
    <div class="stat-tile">
      <div class="stat-label">encoder_count — raw #40003 (reference only)</div>
      <div class="stat-value" id="raw-count">--</div>
    </div>
  </div>

  <h3>Pulse Log</h3>
  <div class="panel">
    <div class="log-list" id="log-list">
      <div class="log-empty">no entries yet — press Log while connected</div>
    </div>
  </div>

  <div id="toasts"></div>

<script>
let pollTimer = null;
let logCount = 0;
let lastStatus = null;

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const btn = document.getElementById("theme-toggle");
  if (btn) btn.textContent = theme === "light" ? "🌙 dark" : "☀ light";
  try { localStorage.setItem("slot-calc-theme", theme); } catch (e) {}
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "dark";
  applyTheme(current === "dark" ? "light" : "dark");
}

(function initTheme() {
  let theme = "dark";
  try { theme = localStorage.getItem("slot-calc-theme") || "dark"; } catch (e) {}
  applyTheme(theme);
})();

function showToast(title, message, kind = "err") {
  const container = document.getElementById("toasts");
  const toast = document.createElement("div");
  toast.className = "toast" + (kind === "ok" ? " ok" : "");
  toast.innerHTML = `<div class="head"><span>${title}</span></div><div class="body"></div>`;
  toast.querySelector(".body").textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 6000);
}

function setStatus(live, text) {
  document.getElementById("status-dot").className = live ? "live" : "";
  document.getElementById("status-text").textContent = text;
  document.getElementById("btn-start").disabled = !live;
  document.getElementById("btn-log").disabled = !live;
  // btn-stop stays enabled only once running -- toggled in startMotor/stopMotor
  if (!live) document.getElementById("btn-stop").disabled = true;
}

function renderStatus(body) {
  lastStatus = body;
  document.getElementById("pulse-value").firstChild.textContent = body.slot_pulse_count;
  document.getElementById("raw-indexer").textContent = body.encoder_indexer_ppr;
  document.getElementById("raw-count").textContent = body.encoder_count;
  const dot = document.getElementById("sensor-dot");
  const text = document.getElementById("sensor-text");
  dot.className = "sensor-dot" + (body.part_sensor ? " on" : "");
  text.textContent = body.part_sensor ? "sensor on" : "sensor off";
}

async function connect() {
  const ip = document.getElementById("ip").value;
  const port = document.getElementById("port").value;
  setStatus(false, "connecting...");
  const res = await fetch("/api/connect", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ip, port})
  });
  const body = await res.json();
  if (res.ok) {
    setStatus(true, `linked :: ${ip}:${port}`);
    if (pollTimer) clearTimeout(pollTimer);
    poll();
  } else {
    setStatus(false, "connection failed");
    showToast("connect failed", body.error || `HTTP ${res.status}`);
  }
}

async function poll() {
  const res = await fetch("/api/status");
  const body = await res.json();
  if (res.ok && body.ok) renderStatus(body);
  pollTimer = setTimeout(poll, 300);
}

async function startMotor() {
  const speed = document.getElementById("speed").value;
  const res = await fetch("/api/start", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({speed})
  });
  const body = await res.json();
  if (!res.ok || !body.ok) {
    showToast("start failed", body.error || `HTTP ${res.status}`);
    return;
  }
  showToast("motor started", `speed=${speed}`, "ok");
  document.getElementById("btn-stop").disabled = false;
}

async function stopMotor() {
  const res = await fetch("/api/stop", {method: "POST"});
  const body = await res.json();
  if (!res.ok || !body.ok) {
    showToast("stop failed", body.error || `HTTP ${res.status}`);
    return;
  }
  showToast("motor stopped", "stop_cmd -> 0", "ok");
  document.getElementById("btn-stop").disabled = true;
}

async function logPulse() {
  const res = await fetch("/api/status");
  const body = await res.json();
  if (!res.ok || !body.ok) {
    showToast("log failed", body.error || `HTTP ${res.status}`);
    return;
  }
  renderStatus(body);
  logCount += 1;

  const list = document.getElementById("log-list");
  const empty = list.querySelector(".log-empty");
  if (empty) empty.remove();

  const entry = document.createElement("div");
  entry.className = "log-entry";
  entry.innerHTML = `
    <span class="key">pulse_${logCount}_log</span>
    <span class="val-group">
      <span class="val">${body.slot_pulse_count}</span>
      <span class="val-sub">encoder_count (#40003) raw: ${body.encoder_count}</span>
    </span>`;
  list.appendChild(entry);
  list.scrollTop = list.scrollHeight;

  showToast(`pulse_${logCount}_log`, `slot=${body.slot_pulse_count} · encoder_count=${body.encoder_count}`, "ok");
}
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, port=5002)
