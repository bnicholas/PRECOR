# Hands-on build guide

Step-by-step walkthrough for wiring and bringing up the CSAFE gateway on a
Raspberry Pi 3B+ with a Precor AMT and RBK (both P80 consoles). Follow it in
order — each step verifies the previous one before you move on.

Estimated bench time end-to-end: one evening.

> ⚠️ Power safety: every time you unplug or re-plug a serial cable, power the
> P80 consoles **off first**. Pin 7 of the CSAFE RJ45 carries 5 V and you don't
> want a hot-swap mishap shorting through the wrong adapter.

---

## 0. Parts check

Lay everything out before you start.

- [ ] Raspberry Pi 3B+, PSU, microSD (≥8 GB, Class 10 or better), keyboard/HDMI or SSH ready
- [ ] 2 × CSAFE cables (RJ45 → DB9-female, pre-wired to CSAFE pinout)
- [ ] 2 × USB ↔ RS-232 adapters (FTDI FT232 preferred)
- [ ] 1 × ethernet cable (or known Wi-Fi) — you'll want reliable networking
- [ ] 1 × laptop on the same LAN for curl + WebSocket tests
- [ ] Multimeter (optional but recommended for the continuity test in §3)

---

## 1. Prep the Raspberry Pi

1. Flash Raspberry Pi OS 64-bit (Bookworm or later) to the SD card with the
   Raspberry Pi Imager. In the imager's advanced options:
   - set hostname `precor.local`
   - enable SSH with your public key
   - pre-configure Wi-Fi if you won't use ethernet
2. Boot the Pi, SSH in:
   ```bash
   ssh pi@precor.local
   ```
3. Update and install build prerequisites:
   ```bash
   sudo apt update && sudo apt -y full-upgrade
   sudo apt -y install git python3-venv python3-pip
   ```
4. Give your user permission to open serial ports:
   ```bash
   sudo usermod -aG dialout $USER
   ```
   Log out and back in so the group takes effect.
5. Reboot.

**Verify:** `groups` should list `dialout`.

---

## 2. Clone and install the server

```bash
git clone <your-fork-url> ~/PRECOR
cd ~/PRECOR
git checkout claude/csafe-fitness-server-xPaba
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
pytest -q           # 26 tests must pass before you touch hardware
```

If those 26 tests don't pass, stop and fix it — the protocol layer is what
everything else depends on.

---

## 3. Sanity-check the adapters (no machines yet)

Plug **one** USB↔RS-232 adapter into the Pi.

1. Find it:
   ```bash
   ls -l /dev/serial/by-id/
   dmesg | tail                 # confirm which /dev/ttyUSBx it became
   ```
   Write the `by-id` path down — you'll use it in the config later.

2. **Loopback test.** On the DB9 end, jumper pin 2 (RXD) to pin 3 (TXD) with a
   short bit of wire or a loopback plug. Then:
   ```bash
   python3 - <<'PY'
   import serial, time
   s = serial.Serial('/dev/ttyUSB0', 9600, timeout=1)
   s.write(b'ping\r\n'); time.sleep(0.1)
   print(repr(s.read(64)))
   PY
   ```
   You should see `b'ping\r\n'` echoed back. If you don't, the adapter is
   dead or the wrong driver is loaded — stop and fix that before wiring
   anything to the P80.

3. Remove the jumper, unplug the first adapter, plug in the second, and
   repeat the loopback test. Record both `by-id` paths.

**Verify:** Two working adapters, two distinct `by-id` paths.

---

## 4. Identify the CSAFE port on each machine

> **Important:** On Precor equipment the CSAFE port is **not** on the P80
> display head. The P80 is just a UI; the RS-232 CSAFE link is exposed by a
> separate I/O board in the machine's base (the "lower PCA" / CSAFE board).
> You'll typically reach it through a small service panel on the frame
> — on the RBK it's under the rear cowl near the base, on the AMT it's
> behind the lower service cover. Some generations route a passthrough cable
> up to a labeled jack near the console, but the jack itself is still wired
> to the lower board.

1. Power each machine off at the wall (not just the console — the lower
   board can still be powered with the display "off").
2. Pop the service panel on the frame and locate the RJ45 labeled **CSAFE**
   on the lower I/O board. Take a photo before you disturb anything so you
   can reverse it cleanly.
3. Route your CSAFE cable through the service panel — if the panel doesn't
   close cleanly over the cable, use a flat RJ45 cable or shim the cover.
   Don't leave the cable pinched against a metal edge.
4. If you're not sure a cable is wired correctly, use a multimeter to check
   continuity between the RJ45 pins and the DB9 pins per the README pinout.
   Key check: **pin 2 of RJ45 → pin 5 of DB9 (GND)** and pin **3 of RJ45 →
   pin 2 of DB9 (RXD at the Pi side)**.

---

## 5. Connect one machine and see bytes

Start with the RBK (bike) — it's easier to sit on while you debug.

1. With the RBK **unplugged at the wall**, open the service panel and plug
   the CSAFE cable into the RJ45 on the lower I/O board. Plug the other end
   into one of the USB↔RS-232 adapters, and the adapter into the Pi.
2. Temporarily close the service panel with the cable routed cleanly,
   re-plug the RBK, and wake the console up by pedaling for a few seconds
   so the P80 enters its normal run state. (The CSAFE board is powered
   from the same bus as the generator/console, so you need a few
   revolutions to get the link alive.)
3. Sniff raw bytes with nothing fancy:
   ```bash
   python3 - <<'PY'
   import serial
   PORT = '/dev/ttyUSB0'       # or your by-id path
   s = serial.Serial(PORT, 9600, timeout=2)
   # Send a CSAFE GETSTATUS:
   #   payload = 0x80, checksum = 0x80, stuffed OK -> F0 80 80 F2
   s.write(bytes.fromhex('F0 80 80 F2'))
   print(s.read(32).hex())
   PY
   ```
   You should see a reply beginning with `F0 …` and ending with `F2`. If it's
   all empty, the most common causes are:
   - TX/RX swapped → try a null-modem adapter or reverse in software
   - Machine not in CSAFE mode → enter the service menu from the P80, set
     the CSAFE comm option on the lower board to **enabled** and equipment
     type to **CSAFE**
   - RBK not generating power → the lower board needs a few seconds of
     pedaling before it will talk
   - Wrong RJ45 jack on the lower board (there can be multiple: CSAFE, TV,
     Ethernet) → double-check the silkscreen label

**Verify:** You see non-empty framed bytes. Move on.

---

## 6. Connect the AMT and wire up the config

1. Power the AMT off, connect the second CSAFE cable + adapter, plug into the
   Pi, power the AMT back on.
2. List the serial adapters and map them to machines:
   ```bash
   ls -l /dev/serial/by-id/
   ```
3. Create `~/PRECOR/.env`:
   ```dotenv
   CSAFE_HOST=0.0.0.0
   CSAFE_PORT=8080
   CSAFE_MACHINES='[
     {"id":"amt","kind":"amt","port":"/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_XXXX-if00-port0","label":"Precor AMT"},
     {"id":"rbk","kind":"rbk","port":"/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_YYYY-if00-port0","label":"Precor RBK"}
   ]'
   ```
   Substitute the real `by-id` paths. If you're not sure which is which,
   unplug one, re-list, and the one that disappeared is the one you
   unplugged — label it physically with tape while you're at it.

---

## 7. First run of the server

```bash
source ~/PRECOR/.venv/bin/activate
csafe-server
```

Expected log lines:

```
INFO     csafe_server.machine: opened amt on /dev/serial/by-id/...
INFO     csafe_server.machine: opened rbk on /dev/serial/by-id/...
INFO     uvicorn.error: Uvicorn running on http://0.0.0.0:8080
```

If a machine fails to open you'll see a single warning, and that machine will
stay in `state: offline` — the server keeps running so you can debug the
other one.

---

## 8. Smoke tests from your laptop

Replace `precor.local` with the Pi's address if mDNS doesn't work.

1. **Liveness:**
   ```bash
   curl -s http://precor.local:8080/healthz
   # {"status":"ok"}
   ```
2. **Machine discovery:**
   ```bash
   curl -s http://precor.local:8080/api/machines | jq
   ```
   Both machines should appear, `connected: true`. `state` will be `ready`,
   `manual`, or `in_use` depending on what the console is doing.
3. **One cached telemetry frame:**
   ```bash
   curl -s http://precor.local:8080/api/machines/rbk/telemetry | jq
   ```
4. **Live telemetry over WebSocket:**
   ```bash
   # requires: pip install websockets
   python3 - <<'PY'
   import asyncio, websockets
   async def main():
       async with websockets.connect('ws://precor.local:8080/ws/machines/rbk/telemetry') as ws:
           for _ in range(5):
               print(await ws.recv())
   asyncio.run(main())
   PY
   ```
   Start pedaling — you should see `speed_kmh`, `cadence_rpm`, and
   `power_watts` climb in real time.

**If telemetry is stuck at nulls** the console is probably responding with an
opcode you didn't request or a different units byte. Run `tail -f` on the
server and look for `poll error` messages; worst case, drop into
`csafe_server/csafe/commands.py` and log the raw payload bytes to see what
the console is actually replying with.

---

## 9. Drive a workout end-to-end

```bash
# Begin a session (RESET → GOREADY → GOINUSE on the console)
curl -s -XPOST http://precor.local:8080/api/machines/rbk/workout/start \
  -H 'content-type: application/json' -d '{"user_label":"ben"}' | jq

# Nudge resistance up
curl -s -XPOST http://precor.local:8080/api/machines/rbk/resistance \
  -H 'content-type: application/json' -d '{"level":8}'

# End and persist
curl -s -XPOST http://precor.local:8080/api/machines/rbk/workout/stop | jq

# Review history
curl -s http://precor.local:8080/api/sessions | jq
```

Expected: the console reacts to `resistance` (you feel it), and after
`stop` the session appears in `/api/sessions` with a populated
`duration_sec`, `distance_m`, `calories`, `avg_power_watts`, and
`avg_hr_bpm` (HR only if you wore a strap).

If resistance doesn't change but no error is returned, the P80 likely wants
a different SET opcode or scaling. See the caveats section in the README.

---

## 10. Install as a service

Once the smoke tests pass, make the server start on boot.

```bash
sudo tee /etc/systemd/system/csafe-server.service > /dev/null <<EOF
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
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now csafe-server
journalctl -u csafe-server -f
```

---

## 11. Point the React Native app at it

In your RN app's config:

```ts
export const API = 'http://precor.local:8080/api';
export const WS  = 'ws://precor.local:8080/ws';
```

Skeleton of a telemetry hook:

```tsx
import { useEffect, useState } from 'react';

export function useTelemetry(machineId: 'amt' | 'rbk') {
  const [t, setT] = useState(null);
  useEffect(() => {
    const ws = new WebSocket(`${WS}/machines/${machineId}/telemetry`);
    ws.onmessage = (ev) => setT(JSON.parse(ev.data));
    return () => ws.close();
  }, [machineId]);
  return t;
}
```

That's it. If the Pi is on the same Wi-Fi as your phone, the app connects
directly; no cloud, no account, no latency beyond the LAN hop.

---

## Troubleshooting quick table

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `failed to open ... on /dev/...` | user not in `dialout`, or device not present | `groups`, `ls /dev/serial/by-id/` |
| Machine stays `offline` after server start | TX/RX swapped, wrong baud, or console not in CSAFE mode | try `9600 8N1`, check P80 service menu |
| Frames arrive but `state: error` | CSAFE state machine out of sync | call `/workout/stop` to force GOFINISHED, then `/workout/start` |
| Telemetry fields all null | console replied with different opcodes than requested | enable debug logging on `poll_loop` and inspect raw payload |
| Resistance command ignored | vendor-specific opcode mismatch | verify with the Precor CSAFE reference for your P80 firmware, adjust `set_resistance` in `csafe_server/machine.py` |
| Adapters swap `/dev/ttyUSBx` on reboot | USB enumeration race | already solved — use `/dev/serial/by-id/...` paths in `CSAFE_MACHINES` |
