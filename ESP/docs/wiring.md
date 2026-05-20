# Wiring — ESP32 ↔ CSAFE

The ESP32's UART pins are **3.3 V TTL**. CSAFE is **RS-232** (±3–15 V,
inverted). You cannot connect them directly — you need a **MAX3232** (or
equivalent) level shifter in between, the same way the Pi gateway uses an
FTDI USB↔RS-232 adapter.

```
 ESP32 (UART2)            MAX3232 breakout            CSAFE RJ45 (machine)
 ┌───────────┐           ┌──────────────┐            ┌──────────────────┐
 │ GPIO17 TX2├──────────▶│ T1IN    T1OUT├───────────▶│ pin 5  RXD (in)  │
 │ GPIO16 RX2│◀──────────│ R1OUT   R1IN │◀───────────│ pin 4  TXD (out) │
 │ 3V3       ├──────────▶│ VCC          │            │ pin 7  GND       │
 │ GND       ├──────────▶│ GND      GND ├────────────┤ (common ground)  │
 └───────────┘           └──────────────┘            └──────────────────┘
```

> The TXD/RXD direction on CSAFE pins 4/5 is **inferred**, not confirmed from
> a public source — the same caveat as the Pi README. If you get no response,
> swap pins 4 and 5. Verify against your Precor service manual.

## CSAFE RJ45 pinout (machine side, lower I/O board)

Mirrors `../../README.md`. Only the three bold rows matter for the ESP32.

| RJ45 pin | Signal (per CSAFE spec)              | Connect to       |
|---------:|-------------------------------------|------------------|
| 1        | Audio Left Input                    | —                |
| 2        | Audio Right Input                   | —                |
| 3        | **Voltage Source Output (4.75–10 V)** | **DO NOT CONNECT** |
| **4**    | Serial data [INFERRED: TXD out]     | MAX3232 R1IN     |
| **5**    | Serial data [INFERRED: RXD in]      | MAX3232 T1OUT    |
| 6        | CTS Flow Control Input              | — (optional)     |
| **7**    | Signal Ground                       | MAX3232 / ESP GND |
| 8        | Shield                              | chassis / shell  |

Framing: **9600 8N1**, no flow control required.

## Safety

- ⚠️ **Pin 3 carries 4.75–10 V.** It is a power-supply *output* from the
  machine meant to power a CSAFE master. Connecting it to the ESP32 (a 3.3 V
  part) or to a MAX3232 signal pin will damage hardware. Leave it insulated
  and unconnected.
- The MAX3232 needs its **GND tied to both** the ESP32 GND and CSAFE pin 7,
  or the signal levels float.
- On the RBK the lower I/O board is **generator-powered** — the CSAFE link is
  dead until you pedal for a few seconds and the console boots. Power the
  ESP32 from USB, not from the machine.

## Powering the ESP32

Use a normal USB supply (the dev board's USB-C/micro-USB). Do not try to
power it from CSAFE pin 3.
