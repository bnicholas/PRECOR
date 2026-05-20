# CSAFE ESP32 Probe

A small, OTA-updatable **ESP32 firmware** that plugs into a Precor machine's
**CSAFE port** and exposes it over Wi-Fi as a Swiss-army-knife HTTP + WebSocket
API. The point is to *make sense of the signals*: poke commands, dump raw
bytes, watch live traffic, and iterate quickly while we build the gaming
prototype — without dragging the whole Raspberry Pi gateway around.

```
┌──────────────┐   CSAFE / RS-232   ┌───────────┐    Wi-Fi    ┌──────────────────┐
│ Precor P80   │◀──────────────────▶│  ESP32 +  │◀───────────▶│ laptop / Pi /    │
│ machine      │  RJ45 → MAX3232    │  MAX3232  │  HTTP + WS  │ game prototype /  │
│ (CSAFE port) │                    │  (probe)  │             │ Claude Code (OTA) │
└──────────────┘                    └───────────┘             └──────────────────┘
```

## How this relates to the Pi gateway

The repo root (`csafe_server/`) is the **production** gateway: a Python async
server on a Raspberry Pi that drives two machines and serves a clean REST/WS
API to the app. This ESP folder is the **bench tool**: cheap, wireless, and
disposable, for reverse-engineering and quick experiments. The CSAFE framing
here is a direct port of `csafe_server/csafe/protocol.py`, so frames are
wire-compatible — what you learn on the ESP transfers straight to the Pi.

## What it does

- Sits on the CSAFE line at 9600 8N1 (re-tunable at runtime).
- Speaks CSAFE for you — framing, byte-stuffing, XOR checksum all automatic.
- Lets you send **raw bytes** or **auto-framed payloads** over HTTP and see
  exactly what the machine replies.
- Decodes the standard telemetry poll (speed, cadence, power, HR, distance,
  calories, elapsed, state).
- Streams **every byte** on the wire over WebSocket for live analysis.
- Updates **over the air** so firmware can be iterated wirelessly.

Full endpoint reference: [`docs/api.md`](docs/api.md). Wiring and safety:
[`docs/wiring.md`](docs/wiring.md).

## Hardware

| Qty | Item | Notes |
|----:|------|-------|
| 1 | ESP32 dev board | Any common ESP32 (e.g. ESP32-DevKitC / WROOM-32). |
| 1 | MAX3232 RS-232 ↔ TTL breakout | TTL side to the ESP32, RS-232 side to CSAFE. |
| 1 | CSAFE RJ45 → flying leads / DB9 | To reach machine pins 4, 5, 7. |
| 1 | USB power supply | Power the ESP32 from USB, **not** from the machine. |

> ⚠️ CSAFE RJ45 **pin 3 carries 4.75–10 V** — never connect it to the ESP32.
> See [`docs/wiring.md`](docs/wiring.md) before wiring anything.

## Build & flash (PlatformIO)

Install [PlatformIO](https://platformio.org/) (`pip install platformio` or the
VS Code extension), then:

```bash
cd ESP
cp include/secrets.example.h include/secrets.h   # then edit in your Wi-Fi
pio run -e usb -t upload                          # first flash over USB
pio device monitor                                # watch it join Wi-Fi, prints its IP
```

Once it's on the network it advertises mDNS as `precor-csafe-esp.local`:

```bash
curl -s http://precor-csafe-esp.local/ | jq
```

## OTA updates (treating the device as its own tool)

After the first USB flash, **all** further updates can go over the air — no
cable. The `ota` build env is preconfigured for this:

```bash
cd ESP
pio run -e ota -t upload      # flashes precor-csafe-esp.local wirelessly
```

If mDNS doesn't resolve on your network, point it at the IP instead:

```bash
pio run -e ota -t upload --upload-port 192.168.1.50
```

The OTA password is set in `include/config.h` (`OTA_PASSWORD`, default
`precor-ota`) and in `platformio.ini`'s `upload_flags`; keep the two in sync
and change them from the default before deploying anywhere shared.

### Letting Claude Code push updates

Claude Code can own the full edit→build→flash loop for this device: change the
firmware in `ESP/`, commit it, then run `pio run -e ota -t upload`. The one
hard requirement is **network reachability** — the OTA push has to originate
from a machine on the **same LAN as the ESP32**. So:

- Running Claude Code **on the Pi** (or any box on your home network): it can
  flash the device directly with the command above.
- Running Claude Code **in the cloud sandbox** (like this session): it can
  write, review and commit firmware, but it can't reach a device on your home
  network — pull the branch on a LAN-connected machine and run the OTA upload
  there (or ask Claude there to do it).

Either way the device is a first-class, remotely-flashable tool in the loop.

## Layout

```
ESP/
├── platformio.ini          board, libs, usb + ota upload envs
├── include/
│   ├── config.h            pins, baud, OTA + Wi-Fi defaults
│   └── secrets.example.h   copy to secrets.h (gitignored) for real creds
├── lib/csafe/              CSAFE framing/opcodes (port of the Pi's protocol.py)
│   ├── csafe.h
│   └── csafe.cpp
├── src/main.cpp            firmware: Wi-Fi, OTA, HTTP + WebSocket API
└── docs/
    ├── wiring.md           ESP32 ↔ MAX3232 ↔ CSAFE + safety
    └── api.md              full endpoint reference
```

## Status

`v0.1.0` — first cut. Untested on real hardware; the CSAFE TXD/RXD pin
direction is inferred (see wiring doc). Treat SET commands as experimental and
verify against your console, exactly as noted in the root README.
