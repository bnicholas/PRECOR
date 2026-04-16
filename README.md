# Precor CSAFE Gateway

A Python async server that exposes the **CSAFE** interface on two Precor P80
consoles (an **AMT** and an **RBK**) over REST + WebSocket so a React Native
app can discover the machines, stream live telemetry, and drive workouts.

Target hardware: Raspberry Pi 3B+ (Raspberry Pi OS, 64-bit).

```
┌──────────────┐      CSAFE / RS-232      ┌───────────────┐
│ Precor AMT   │◀────────────────────────▶│               │
│ (P80 console)│      RJ45 → DB9 → USB    │  Raspberry Pi │   Wi-Fi / LAN   ┌──────────────┐
├──────────────┤                          │     3B+       │◀───────────────▶│ React Native │
│ Precor RBK   │◀────────────────────────▶│   csafe-server│   REST + WS     │     app      │
│ (P80 console)│                          │  :8080        │                 └──────────────┘
└──────────────┘                          └───────────────┘
```

---

## 1. Hardware BOM

You need to wire each machine's CSAFE port to a serial port on the Pi. CSAFE is
standard RS-232 (not TTL, not USB), presented on an **RJ45 jack** labeled
"CSAFE" on the machine's **lower I/O board** — not on the P80 console itself.
The P80 is just the display head; the CSAFE link is exposed by a separate PCA
in the machine's base, reachable through a service panel on the frame (under
the rear cowl on the RBK, behind the lower service cover on the AMT).

| Qty | Item | Notes |
|----:|------|-------|
| 2   | CSAFE RJ45 → DB9 female cable | Sold as "CSAFE cable" or "Polar / Precor CSAFE adapter". Pre-wired for the CSAFE pinout below. |
| 2   | USB ↔ RS-232 adapter (FTDI FT232 based) | Genuine FTDI recommended; avoid PL2303 clones on the Pi. Provides `/dev/ttyUSBx`. |
| 1   | Powered USB hub (optional) | If you already use the Pi's USB for peripherals. |
| 1   | Raspberry Pi 3B+ with PSU and microSD (≥8 GB) | Running Raspberry Pi OS 64-bit (bookworm or later). |

Alternative (saves one USB port): use the Pi's built-in UART (`/dev/serial0`,
GPIO 14 TX / GPIO 15 RX) for one machine via a **3.3 V TTL ↔ RS-232 level
shifter** (MAX3232 breakout). Do **not** wire RS-232 directly to the Pi GPIO —
you'll destroy the SoC. The default config assumes two USB adapters, which is
simpler and safer.

### CSAFE RJ45 pinout (machine side — lower I/O board)

| RJ45 pin | Signal    | DB9 pin (DCE) |
|---------:|-----------|---------------|
| 1        | (reserved)| —             |
| 2        | GND       | 5             |
| 3        | TXD (out of console) | 2 (RXD at the PC) |
| 4        | RXD (into console)   | 3 (TXD at the PC) |
| 5        | GND       | 5             |
| 6        | (reserved)| —             |
| 7        | +5 V (do not connect to the adapter) | — |
| 8        | (reserved)| —             |

Framing: **9600 8N1**, no flow control. A straight (non-null-modem) RJ45→DB9
cable paired with a standard USB↔RS-232 adapter is what you want; the
machine is a DTE talking to the Pi as DCE.

> ⚠️ Pin 7 carries 5 V from the machine's lower board. **Do not** bring it
> into a 3.3 V UART or into an adapter that isn't expecting it. A commercial
> CSAFE cable omits or isolates pin 7.

> On the RBK specifically, the lower I/O board is generator-powered — the
> CSAFE link won't come alive until you've pedaled for a few seconds and the
> console has booted.

---

## 2. Install

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip

git clone <this repo> && cd PRECOR
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

Add your user to `dialout` so the server can open `/dev/ttyUSB*` without sudo:

```bash
sudo usermod -aG dialout $USER
# log out / log in once
```

Check the adapters:

```bash
ls -l /dev/serial/by-id/
# usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0 -> ../../ttyUSB0
# usb-FTDI_FT232R_USB_UART_A50285BK-if00-port0 -> ../../ttyUSB1
```

Prefer the stable `/dev/serial/by-id/...` paths over `/dev/ttyUSBx` — the USB
enumeration order isn't guaranteed across reboots.

---

## 3. Configure

Create a `.env` in the repo root (optional — the defaults assume
`/dev/ttyUSB0` for AMT and `/dev/ttyUSB1` for RBK):

```dotenv
CSAFE_HOST=0.0.0.0
CSAFE_PORT=8080
CSAFE_TELEMETRY_INTERVAL=1.0
CSAFE_COMMAND_TIMEOUT=1.5
CSAFE_DB_PATH=/var/lib/csafe/csafe.sqlite

# JSON-encoded list; use `/dev/serial/by-id/...` for stability.
CSAFE_MACHINES='[
  {"id":"amt","kind":"amt","port":"/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0","label":"Precor AMT 835"},
  {"id":"rbk","kind":"rbk","port":"/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A50285BK-if00-port0","label":"Precor RBK 835"}
]'
```

---

## 4. Run

```bash
csafe-server            # or: python -m csafe_server.main
```

Server listens on `http://<pi-ip>:8080`. OpenAPI docs at `/docs`.

To run on boot, drop this `systemd` unit at `/etc/systemd/system/csafe-server.service`:

```ini
[Unit]
Description=Precor CSAFE Gateway
After=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/PRECOR
EnvironmentFile=/home/pi/PRECOR/.env
ExecStart=/home/pi/PRECOR/.venv/bin/csafe-server
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now csafe-server
```

---

## 5. REST API

All endpoints live under `/api`. JSON in/out.

| Method | Path | Purpose |
|-------|------|---------|
| GET   | `/api/machines` | List configured machines and their current state. |
| GET   | `/api/machines/{id}` | One machine's info. |
| GET   | `/api/machines/{id}/telemetry` | Latest cached telemetry sample. |
| POST  | `/api/machines/{id}/workout/start` | Begin a session (body: `{user_label?}`). Returns `session_id`. |
| POST  | `/api/machines/{id}/workout/pause` | Send GOFINISHED to the console. |
| POST  | `/api/machines/{id}/workout/stop`  | End and persist the session. |
| POST  | `/api/machines/{id}/resistance` | `{level: 1..30}` — maps to CSAFE `SETGEAR`. |
| POST  | `/api/machines/{id}/target-power` | `{watts: 0..2000}` — maps to `SETPOWER`. |
| POST  | `/api/machines/{id}/speed` | `{kmh: 0..40}` — maps to `SETSPEED`. |
| GET   | `/api/sessions?limit=50` | Session history (most recent first). |
| GET   | `/healthz` | Liveness probe. |

### Example

```bash
curl -s http://pi.local:8080/api/machines | jq
curl -s -XPOST http://pi.local:8080/api/machines/rbk/workout/start \
     -H 'content-type: application/json' -d '{"user_label":"ben"}'
curl -s -XPOST http://pi.local:8080/api/machines/rbk/target-power \
     -H 'content-type: application/json' -d '{"watts":180}'
```

---

## 6. WebSocket telemetry

Connect to `ws://<pi>:8080/ws/machines/{id}/telemetry`. Messages are JSON of
shape `Telemetry`:

```json
{
  "machine_id": "rbk",
  "timestamp": "2026-04-15T12:34:56.789Z",
  "state": "in_use",
  "elapsed_sec": 322,
  "distance_m": 1850.0,
  "calories": 74,
  "speed_kmh": 28.6,
  "cadence_rpm": 89,
  "heart_rate_bpm": 148,
  "power_watts": 182,
  "grade_pct": null
}
```

React Native sketch:

```ts
const ws = new WebSocket(`ws://${PI_HOST}:8080/ws/machines/rbk/telemetry`);
ws.onmessage = (ev) => setTelemetry(JSON.parse(ev.data));
```

---

## 7. Project layout

```
csafe_server/
├── main.py             FastAPI entrypoint + lifespan
├── config.py           Settings + machine wiring table
├── models.py           Pydantic DTOs shared by API + DB
├── manager.py          MachineManager (owns machines, sessions)
├── machine.py          Async per-machine serial + poll loop
├── db.py               aiosqlite session + samples store
├── api/
│   ├── rest.py         REST endpoints
│   └── ws.py           WebSocket telemetry
└── csafe/
    ├── protocol.py     Framing, byte-stuffing, checksum, FrameReader
    └── commands.py     Opcodes, encode_commands, parse_response
tests/
├── test_protocol.py    Framing/stuffing/checksum (hardware-free)
└── test_commands.py    Command encoding + response parsing
```

---

## 8. CSAFE notes and caveats

* **Framing** is implemented against the public CSAFE spec: `F0` start
  (`F1` for extended), `F2` end, `F3` escape, payload + XOR checksum in
  between, with reserved bytes stuffed as `F3 (b - 0xF0)`.
* **Telemetry opcodes** used by the polling loop (`GETSTATUS`, `GETTWORK`,
  `GETHORIZONTAL`, `GETCALORIES`, `GETSPEED`, `GETCADENCE`, `GETHRCUR`,
  `GETPOWER`) are standard CSAFE and have been observed to work on P80
  firmwares.
* **Control opcodes** (`SETGEAR`, `SETPOWER`, `SETSPEED`) are **standard
  CSAFE but vendor-specific in practice**. The P80 accepts these on supported
  firmware, but exact units/ranges can differ. Verify against your console
  before wiring them to user-facing controls, and tweak
  `csafe_server/machine.py` if the scaling is off.
* The P80's CSAFE state machine expects a sequence before it takes SET
  commands: `RESET → GOREADY → GOINUSE`. `start_session` does this for you.
* If a console ignores control commands outright, check that the P80 is set
  to **"CSAFE" (not "ADA") equipment mode** in its service menu.

---

## 9. Development

```bash
.venv/bin/pytest -q            # 26 tests, hardware-free
.venv/bin/ruff check csafe_server tests
```

The protocol and parser layers have no hardware dependency, so CI on a
laptop covers the risky bits. Integration testing requires the Pi + a live
console.
