# ESP-NOW receiver (game-host bridge)

A self-contained PlatformIO project for a **second** ESP32. It listens for the
CSAFE probe's ESP-NOW telemetry broadcasts and prints each one as a JSON line
over USB serial — turning the wireless telemetry into something a laptop or
game can read from `/dev/ttyUSB*`.

```
[machine] ──CSAFE──▶ [probe ESP32] ──ESP-NOW──▶ [receiver ESP32] ──USB JSON──▶ [game host]
```

## Build & flash

```bash
cd ESP/examples/espnow_receiver
pio run -t upload
pio device monitor          # 115200 baud
```

## The one gotcha: channel must match

ESP-NOW peers only hear each other **on the same Wi-Fi channel**. The probe,
while connected as a Wi-Fi STA, runs on its access point's channel. So:

1. On the probe: `curl http://precor-csafe-esp.local/ | jq .wifi.channel`
2. Re-flash the receiver pinned to that channel:

```bash
pio run -t upload -e esp32dev -a "-DRX_CHANNEL=6"   # if the probe is on ch 6
```

   (or set `-DRX_CHANNEL=6` in `platformio.ini` and re-flash).

If you see nothing, a channel mismatch is the first thing to check.

## Enabling the broadcast on the probe

ESP-NOW is off by default. Turn it on:

```bash
curl -s -XPOST http://precor-csafe-esp.local/espnow \
     -H 'content-type: application/json' -d '{"enabled":true,"interval_ms":250}'
```

## Output

One JSON object per received packet:

```json
{"src":"AA:BB:CC:DD:EE:FF","seq":42,"status":2,"heart_rate_bpm":148,
 "cadence_rpm":89,"power_watts":182,"speed_kmh":28.6,"calories":74,
 "distance_m":1850,"elapsed_sec":322}
```

`status` is the CSAFE state nibble; `seq` is the probe's monotonic counter
(gaps = dropped packets). Absent telemetry fields arrive as `0`.
