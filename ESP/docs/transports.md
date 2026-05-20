# Wireless transports

The probe's debug/control surface is Wi-Fi HTTP + WebSocket (see `api.md`).
That's the right tool for development. For the *game* link there are several
ESP wireless options; this is the running notes on what we use and what's on
the table.

## Implemented

### Wi-Fi HTTP + WebSocket (debug surface)
What the probe exposes today. Mirrors the Pi gateway's JSON, easy to call from
a laptop or browser prototype. Keep this as the dev/debug path regardless of
what the game uses.

### ESP-NOW telemetry broadcast (game link)
Connectionless, ~1–2 ms, peer-to-peer over the Wi-Fi radio — no AP, no pairing.
The probe broadcasts a compact 24-byte `TelemetryPacket`
(`include/telemetry_packet.h`) that a game host consumes via
`examples/espnow_receiver`. Off by default; toggle with `POST /espnow`.

- **Pro:** lowest latency, no infrastructure, coexists with the Wi-Fi STA.
- **Con:** custom format; receiver must sit on the probe's Wi-Fi channel
  (the AP's channel while connected as STA). Broadcast is unencrypted.
- **Next:** optional bidirectional control (game → probe `SETPOWER`/`SETGEAR`),
  and a fixed-channel "ESP-NOW only" mode that drops the STA association for
  deterministic latency.

## On the table (not built)

### BLE — Fitness Machine Service (FTMS)
The Bluetooth SIG standard GATT service real fitness apps/games (Zwift, etc.)
already speak. Exposing the machine as a BLE FTMS device would let off-the-shelf
games connect with zero custom integration — likely the highest-leverage option
if we want to ride existing software.

- **Pro:** standards-based; phones/tablets connect directly, no Wi-Fi.
- **Con:** constrained to the FTMS data model; original ESP32 is BLE 4.2
  (newer C-series have BLE 5 long-range). Lower throughput than ESP-NOW.

### Newer silicon: ESP32-C6 / ESP32-H2
Add **Wi-Fi 6** (C6) and an **802.15.4** radio → **Thread / Zigbee / Matter**,
plus **BLE 5**. Mostly smart-home oriented; only worth it if we want Matter or
mesh-grade reliability. Would mean changing the `board` in `platformio.ini`.

### ESP-MESH / Wi-Fi mesh
Self-forming multi-node mesh — relevant only once several machines are wired and
we want them to relay without per-device AP config.

## Rule of thumb

- Building/debugging → **Wi-Fi HTTP/WS** (already here).
- Custom low-latency game host → **ESP-NOW** (already here).
- Plug into existing fitness games → **BLE FTMS** (future).
- Matter/Thread/mesh → **ESP32-C6/H2** (future, needs new hardware).
