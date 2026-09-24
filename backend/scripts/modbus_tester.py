"""
Modbus TCP register checker — Flask + pymodbus.
Registers are defined once in REGISTERS; UI is generated from this dict.

Register map below mirrors app/plc/registers.py / machine_config.yaml's
`plc.registers` block (the instrumentation team's sheet) — literal Modicon
4xxxx numbers, holding-register table throughout (no coils in the confirmed
sheet). `strobe_reg` (per-camera) and the exit-station `result_write`
registers use a different, unconfirmed addressing scheme and are
deliberately left out here rather than guessed — see machine_config.yaml
and CLAUDE.md's "ask, don't invent" rule.

pip install flask pymodbus
"""

import struct
import threading
from flask import Flask, request, jsonify, render_template_string
from pymodbus.client import ModbusTcpClient

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Register config — this is the only place you need to edit to add registers.
#   modicon : literal Modicon 4xxxx number, as given by the instrumentation
#             team's sheet (app/plc/registers.py is the source of truth)
#   type    : "bool" | "int" | "long" (32-bit, 2 registers) | "float" (32-bit, 2 registers)
#   access  : "r" | "w" | "rw"
#   table   : "coil" (bool only) | "holding" (int/long/float, and bool too —
#             the OSM sheet is all holding registers, nothing here is a coil)
# ---------------------------------------------------------------------------
MODBUS_ADDRESS_OFFSET = 40001  # config stores the literal 4xxxx number; pymodbus wants 0-based

REGISTERS = {
    "pulse_count":             {"modicon": 40001, "type": "int",  "access": "r",  "table": "holding", "desc": "Encoder actual pulse"},
    "encoder_indexer_ppr":     {"modicon": 40002, "type": "int",  "access": "r",  "table": "holding", "desc": "Reset to 0 at indexer revolution"},
    "encoder_count":           {"modicon": 40003, "type": "long", "access": "r",  "table": "holding", "desc": "Total pulses, machine start to stop"},
    "part_sensor":             {"modicon": 40004, "type": "bool", "access": "r",  "table": "holding", "desc": "Part detection at entry"},
    "heartbeat":               {"modicon": 40005, "type": "int",  "access": "r",  "table": "holding", "desc": "Per-slot heartbeat tick count (1,2,3...)"},
    "indexing_pulse":          {"modicon": 40006, "type": "bool", "access": "r",  "table": "holding", "desc": "0/1 after reset bit sent"},
    "heartbeat_per_slot":      {"modicon": 40007, "type": "int",  "access": "rw", "table": "holding", "desc": "PC-configured heartbeat cadence (pulses)"},
    "indexing_pulse_per_slot": {"modicon": 40008, "type": "int",  "access": "rw", "table": "holding", "desc": "PC-configured pulses-per-slot"},
    "reject_cmd":              {"modicon": 40009, "type": "bool", "access": "rw", "table": "holding", "desc": "Rejected-part command"},
    "stop_cmd":                {"modicon": 40010, "type": "bool", "access": "rw", "table": "holding", "desc": "Run/stop (1=run, 0=halt)"},
    "speed_setpoint":          {"modicon": 40011, "type": "int",  "access": "rw", "table": "holding", "desc": "Motor speed, 0-1000 scale"},
    "fault":                   {"modicon": 40012, "type": "int",  "access": "rw", "table": "holding", "desc": "Fault register (R/W both sides per sheet)"},
}
for _cfg in REGISTERS.values():
    _cfg["address"] = _cfg["modicon"] - MODBUS_ADDRESS_OFFSET  # 0-based protocol address for pymodbus

STATE = {"client": None, "lock": threading.Lock()}


def get_client() -> ModbusTcpClient:
    if STATE["client"] is None:
        raise RuntimeError("Not connected")
    return STATE["client"]


def decode_float(regs):
    # 2 x 16-bit holding regs -> 32-bit float (big-endian word order)
    packed = struct.pack(">HH", regs[0], regs[1])
    return struct.unpack(">f", packed)[0]


def encode_float(value):
    packed = struct.pack(">f", float(value))
    return list(struct.unpack(">HH", packed))


def decode_long(regs):
    # 2 x 16-bit holding regs -> unsigned 32-bit int (big-endian word order)
    packed = struct.pack(">HH", regs[0], regs[1])
    return struct.unpack(">I", packed)[0]


def encode_long(value):
    packed = struct.pack(">I", int(value))
    return list(struct.unpack(">HH", packed))


@app.route("/")
def index():
    return render_template_string(PAGE, registers=REGISTERS)


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
    return jsonify({"ok": True})


@app.route("/api/read", methods=["GET"])
def read_all():
    result = {}
    with STATE["lock"]:
        client = get_client()
        for name, cfg in REGISTERS.items():
            try:
                if cfg["table"] == "coil":
                    rr = client.read_coils(cfg["address"], count=1)
                    result[name] = bool(rr.bits[0]) if not rr.isError() else None
                elif cfg["type"] == "float":
                    rr = client.read_holding_registers(cfg["address"], count=2)
                    result[name] = None if rr.isError() else decode_float(rr.registers)
                elif cfg["type"] == "long":
                    rr = client.read_holding_registers(cfg["address"], count=2)
                    result[name] = None if rr.isError() else decode_long(rr.registers)
                elif cfg["type"] == "bool":
                    rr = client.read_holding_registers(cfg["address"], count=1)
                    result[name] = None if rr.isError() else bool(rr.registers[0])
                else:  # int
                    rr = client.read_holding_registers(cfg["address"], count=1)
                    result[name] = None if rr.isError() else rr.registers[0]
            except Exception as exc:
                result[name] = None
    return jsonify(result)


@app.route("/api/write", methods=["POST"])
def write_one():
    data = request.get_json()
    name, value = data["name"], data["value"]
    cfg = REGISTERS.get(name)
    if not cfg or "w" not in cfg["access"]:
        return jsonify({"ok": False, "error": "not writable"}), 400

    with STATE["lock"]:
        try:
            client = get_client()
            if cfg["table"] == "coil":
                rr = client.write_coil(cfg["address"], bool(value))
            elif cfg["type"] == "float":
                rr = client.write_registers(cfg["address"], encode_float(value))
            elif cfg["type"] == "long":
                rr = client.write_registers(cfg["address"], encode_long(value))
            elif cfg["type"] == "bool":
                rr = client.write_register(cfg["address"], 1 if value else 0)
            else:
                rr = client.write_register(cfg["address"], int(value))
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        if rr.isError():
            return jsonify({"ok": False, "error": str(rr)}), 400
    return jsonify({"ok": True})


PAGE = """
<!doctype html>
<html>
<head>
<title>MODBUS :: REGISTER CONSOLE</title>
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
    padding: 8px 16px;
    border-radius: 3px;
    border: 1px solid var(--accent);
    cursor: pointer;
    font-family: inherit;
    font-size: 12px;
    letter-spacing: 1px;
    text-transform: uppercase;
    transition: background 0.15s, box-shadow 0.15s;
  }
  button:hover { background: var(--accent-dim); box-shadow: 0 0 10px var(--accent-dim); }
  button:disabled { opacity: 0.3; cursor: not-allowed; }
  #theme-toggle {
    color: var(--text-dim);
    border-color: var(--border);
    white-space: nowrap;
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

  .row {
    display: grid;
    grid-template-columns: 260px 1fr auto;
    align-items: center;
    gap: 14px;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: 3px;
    margin: 6px 0;
    background: var(--panel);
  }
  .row .name { color: var(--accent); font-size: 13px; }
  .row .name .regnum { color: var(--text-dim); font-size: 11px; font-weight: normal; }
  .row .meta { color: var(--text-dim); font-size: 10px; letter-spacing: 1px; text-transform: uppercase; }
  .row .desc { color: var(--text-dim); font-size: 10px; margin-top: 2px; text-transform: none; letter-spacing: 0.2px; }
  .row input[type=number] { width: 100%; }

  .indicator {
    width: 64px; height: 28px;
    border-radius: 3px;
    border: 1px solid var(--border);
    display: flex; align-items: center; justify-content: center;
    font-size: 10px; letter-spacing: 1px; font-weight: bold;
  }
  .indicator.on { background: var(--accent-dim); border-color: var(--accent); color: var(--accent); box-shadow: 0 0 10px var(--accent-dim); }
  .indicator.off { background: var(--danger-dim); border-color: var(--danger); color: var(--danger); }
  .indicator.on::after { content: "ON"; }
  .indicator.off::after { content: "OFF"; }

  #toasts {
    position: fixed;
    top: 20px;
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    z-index: 999;
    pointer-events: none;
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
      <h2>Modbus Register Console</h2>
      <div class="subtitle">TCP // OSM PC&lt;-&gt;PLC holding register I/O — dev tool, not for production PLCs</div>
    </div>
    <button id="theme-toggle" onclick="toggleTheme()">☀ light</button>
  </div>

  <div class="panel conn-row">
    <span id="status-dot"></span>
    <span class="status-text" id="status-text">disconnected</span>
    <div class="label">ip</div>
    <input id="ip" type="text" value="192.168.7.72">
    <div class="label">port</div>
    <input id="port" type="text" value="502">
    <button onclick="connect()">Connect</button>
  </div>

  <h3>Registers</h3>
  <div id="regs"></div>

  <div id="toasts"></div>

<script>
const REGISTERS = {{ registers | tojson }};

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const btn = document.getElementById("theme-toggle");
  if (btn) btn.textContent = theme === "light" ? "🌙 dark" : "☀ light";
  try { localStorage.setItem("modbus-tester-theme", theme); } catch (e) {}
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "dark";
  applyTheme(current === "dark" ? "light" : "dark");
}

(function initTheme() {
  let theme = "dark";
  try { theme = localStorage.getItem("modbus-tester-theme") || "dark"; } catch (e) {}
  applyTheme(theme);
})();

function buildRows() {
  const container = document.getElementById("regs");
  container.innerHTML = "";
  for (const [name, cfg] of Object.entries(REGISTERS)) {
    const row = document.createElement("div");
    row.className = "row";
    row.id = "row-" + name;

    const label = document.createElement("div");
    label.innerHTML = `<div class="name">${name} <span class="regnum">#${cfg.modicon}</span></div><div class="meta">addr ${cfg.address} · ${cfg.type} · ${cfg.access} · ${cfg.table}</div><div class="desc">${cfg.desc || ""}</div>`;
    row.appendChild(label);

    if (cfg.type === "bool") {
      const indicator = document.createElement("div");
      indicator.className = "indicator off";
      indicator.id = "ind-" + name;
      row.appendChild(indicator);

      if (cfg.access.includes("w")) {
        const btn = document.createElement("button");
        btn.textContent = "Toggle";
        btn.onclick = () => toggleBool(name);
        row.appendChild(btn);
      } else {
        row.appendChild(document.createElement("div"));
      }
    } else {
      const input = document.createElement("input");
      input.type = "number";
      input.step = cfg.type === "float" ? "any" : "1";
      input.id = "val-" + name;
      row.appendChild(input);

      if (cfg.access.includes("w")) {
        const btn = document.createElement("button");
        btn.textContent = "Write";
        btn.onclick = () => writeValue(name);
        row.appendChild(btn);
      } else {
        row.appendChild(document.createElement("div"));
      }
    }
    container.appendChild(row);
  }
}

function showToast(title, message, kind = "err") {
  const container = document.getElementById("toasts");
  const toast = document.createElement("div");
  toast.className = "toast" + (kind === "ok" ? " ok" : "");
  toast.innerHTML = `<div class="head"><span>${title}</span></div><div class="body"></div>`;
  toast.querySelector(".body").textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 500);
}

function setStatus(live, text) {
  document.getElementById("status-dot").className = live ? "live" : "";
  document.getElementById("status-text").textContent = text;
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
    buildRows();
    poll();
  } else {
    setStatus(false, "connection failed");
    showToast("connect failed", body.error || `HTTP ${res.status}`);
  }
}

async function poll() {
  const res = await fetch("/api/read");
  const data = await res.json();
  for (const [name, value] of Object.entries(data)) {
    const cfg = REGISTERS[name];
    if (cfg.type === "bool") {
      const ind = document.getElementById("ind-" + name);
      if (ind) ind.className = "indicator " + (value ? "on" : "off");
    } else {
      const input = document.getElementById("val-" + name);
      if (input && document.activeElement !== input) input.value = value;
    }
  }
  setTimeout(poll, 250);  // 4x/s so encoder pulses are visible moving
}

async function toggleBool(name) {
  const ind = document.getElementById("ind-" + name);
  const current = ind.className.includes("on");
  const res = await fetch("/api/write", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({name, value: !current})
  });
  const body = await res.json();
  if (!res.ok || !body.ok) showToast(`write failed: ${name}`, body.error || `HTTP ${res.status}`);
  else showToast(`write ok: ${name}`, `-> ${!current}`, "ok");
}

async function writeValue(name) {
  const val = document.getElementById("val-" + name).value;
  const res = await fetch("/api/write", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({name, value: val})
  });
  const body = await res.json();
  if (!res.ok || !body.ok) showToast(`write failed: ${name}`, body.error || `HTTP ${res.status}`);
  else showToast(`write ok: ${name}`, `-> ${val}`, "ok");
}
</script>
</body>
</html>
"""

if __name__ == "__main__":
    # Local only, no debugger: Werkzeug debug mode on 0.0.0.0 lets anyone on
    # the network run code on this PC.
    app.run(host="127.0.0.1", debug=False, port=5001)
