# API reference

Base URL: `http://precor-csafe-esp.local` (or the device IP). All responses are
JSON; CORS is open (`Access-Control-Allow-Origin: *`) so a browser prototype
can call it directly.

The device speaks CSAFE for you: framing (`F0 … F2`), byte-stuffing and the XOR
checksum are applied automatically on `/csafe/frame` and `/csafe/telemetry`.
Use `/csafe/raw` when you want full control over the exact bytes on the wire.

---

## GET `/`

Device + link status.

```json
{
  "firmware": "0.1.0",
  "device": "precor-csafe-esp",
  "uptime_ms": 123456,
  "free_heap": 210000,
  "wifi": { "ssid": "...", "ip": "192.168.1.50", "rssi": -57, "channel": 6,
            "mac": "AA:BB:CC:DD:EE:FF" },
  "csafe": { "baud": 9600, "rx_pin": 16, "tx_pin": 17 },
  "espnow": { "enabled": false, "ready": true, "interval_ms": 250, "seq": 0 }
}
```

`wifi.channel` is the channel an ESP-NOW receiver must match (see below).

## GET `/health`

`{ "ok": true }` — liveness probe.

## GET `/csafe/telemetry`

Sends the standard poll (`GETSTATUS, GETTWORK, GETHORIZONTAL, GETCALORIES,
GETSPEED, GETCADENCE, GETHRCUR, GETPOWER`) and decodes the reply.

```json
{
  "ok": true,
  "rx_frame": "F1...F2",
  "status": 2,
  "fields": {
    "elapsed_sec": 322,
    "distance_m": 1850,
    "calories": 74,
    "speed_kmh": 28.6,
    "cadence_rpm": 89,
    "heart_rate_bpm": 148,
    "power_watts": 182
  }
}
```

`status` is the CSAFE state nibble (1=ready, 2=in_use, 3=paused, 4=finished).

## POST `/csafe/raw`

Send arbitrary bytes; get whatever comes back. The primary "make sense of the
signals" tool — nothing is interpreted.

Request:

```json
{ "hex": "F0 80 80 F2", "timeout_ms": 300 }
```

`hex` tolerates spaces, commas and colons as separators. `timeout_ms` is
optional (default 300); the read also returns early after ~60 ms of silence.

Response:

```json
{ "tx": "F08080F2", "rx": "F1...F2", "rx_len": 18 }
```

## POST `/csafe/frame`

Give it a **payload** (opcodes + data, no framing) and it builds the full CSAFE
frame, sends it, and tries to parse the response frame.

Request — here `8081` is `GETSTATUS` + `RESET`:

```json
{ "payload": "8081", "extended": false, "timeout_ms": 300 }
```

Response:

```json
{
  "tx_payload": "8081",
  "tx_frame": "F08081...F2",
  "rx_frame": "F1...F2",
  "rx_ok": true,
  "rx_payload": "02A0..."
}
```

For long (SET) commands the payload is `opcode, length, data…`. Example —
`SETPOWER` (0x34) to 180 W (`B4 00` little-endian, length 2): payload
`3402B400`.

## POST `/serial/config`

Re-tune the UART without reflashing — handy for probing whether a port is
actually 9600.

```json
{ "baud": 9600 }
```

## POST `/espnow`

Enable/disable the ESP-NOW telemetry broadcast and set its cadence. When
enabled the probe polls the machine every `interval_ms` and broadcasts a
24-byte `TelemetryPacket` (see `../include/telemetry_packet.h`) to all ESP-NOW
peers on the current Wi-Fi channel. Off by default.

Request (both fields optional):

```json
{ "enabled": true, "interval_ms": 250 }
```

Response:

```json
{
  "enabled": true,
  "ready": true,
  "interval_ms": 250,
  "channel": 6,
  "mac": "AA:BB:CC:DD:EE:FF",
  "payload_bytes": 24
}
```

`interval_ms` minimum is 20. Receiver setup and the channel-matching gotcha are
covered in `../examples/espnow_receiver/README.md` and `transports.md`.

---

## WebSocket `ws://<device>:81`

Every byte seen on the CSAFE line is pushed as it happens:

```json
{ "dir": "tx", "hex": "F08080F2" }
{ "dir": "rx", "hex": "F102A0..." }
```

`tx` = bytes the probe sent, `rx` = bytes received (including unsolicited
traffic when the probe is wired as a passive tap). The stream is read-only;
messages sent to the socket are ignored.

---

## curl quickstart

```bash
DEV=precor-csafe-esp.local

curl -s http://$DEV/ | jq
curl -s http://$DEV/csafe/telemetry | jq
curl -s -XPOST http://$DEV/csafe/raw   -H 'content-type: application/json' -d '{"hex":"F08080F2"}' | jq
curl -s -XPOST http://$DEV/csafe/frame -H 'content-type: application/json' -d '{"payload":"80"}' | jq
```
