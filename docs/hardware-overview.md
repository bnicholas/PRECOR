# Hardware architecture — Precor RBK / AMT

> **Source discipline.** Every claim below is tagged:
>
> - **[VERIFIED]** — taken from an authoritative public source, cited inline.
> - **[INFERRED]** — an engineering deduction I made from observable
>   behaviour or general principles of similar equipment. Treat as a
>   hypothesis until a service manual or a multimeter confirms it.
> - **[UNKNOWN]** — I could not find this in public sources and did not
>   observe it. Look it up in the service manual or measure it.
>
> The authoritative reference for everything here is the **Precor service
> manual** for your specific model. I could not fetch these from this
> sandbox (outbound requests to the hosting sites are blocked), so I have
> not read them myself. Links in §7.

Answer to the obvious question: yes, the **P80 is essentially a computer**
— **[VERIFIED]** it uses a TI OMAP ARM-class SoC, 15-inch HD touchscreen,
Bluetooth and Wi-Fi ([Precor P80 service manual references][p80]). It runs
its own UI software and talks to the lower I/O board downstream over CSAFE.
Retiring it means replacing the UI and the keypad input path; the lower
board keeps doing the real work.

---

## 1. CSAFE protocol

**[VERIFIED]** from the Wikipedia summary of the FitLinxx-authored
specification [csafe-wiki]:

- Developed in 1997 by FitLinxx; stewarded by a CSAFE group inside FISA
  (Fitness Industry Suppliers Association) since October 2000.
- Physical layer: **RS-232, 9600 baud, 8 data bits, 1 stop bit, no parity**.
- Connector: **8P8C (RJ-45)** jack on the machine — "*although the wiring
  scheme has no relation to ethernet*".
- Two frame modes: **standard** and **extended**. Extended mode adds
  source/destination address fields and is meant for installations where
  one computer multiplexes onto many machines.
- Master/slave architecture.

**[INFERRED from my existing protocol tests + Concept2's public CSAFE
implementation]** the framing bytes `F0`/`F1`/`F2`/`F3`, the XOR checksum,
and the `F3 (b − 0xF0)` byte-stuffing rule. These are consistent with
multiple open-source CSAFE implementations (including the Node.js module
linked under [csafe-wiki]'s external references) but the exact wording
comes from the spec PDF, which I have not been able to fetch from here.
Our 26 unit tests round-trip correctly, so at minimum our implementation
is internally consistent.

**[UNKNOWN]** precise data-format definitions for every GET/SET opcode on
the Precor P80. Get a copy of the CSAFE spec and the P80 service manual's
"CSAFE command reference" section and cross-check against
`csafe_server/csafe/commands.py` before trusting SET commands in
production.

---

## 2. Resistance and power system — RBK

**[VERIFIED]** from Precor's own product spec sheet for the RBK 835
[precor-rbk835-spec]:

> "3-Phase Generator / Eddy Current Resistance System. … the 3-phase
> generator / eddy current resistance system requires no backup battery in
> order to efficiently power the bike, which means it is self-powered."

Two concrete facts from that quote:

1. The resistance element is called a **3-phase generator / eddy current
   resistance system** by Precor. It's a single integrated system, not a
   separate generator plus a separate brake.
2. It is **self-powered**. No wall plug, no battery. The user pedaling is
   both the power source and the thing being resisted.

### What "3-phase generator / eddy current resistance system" means

**[INFERRED]** — Precor's marketing term compresses several things, and
without the service-manual schematic I can only sketch the general idea.
Here is the hypothesis that best fits a self-powered cardio machine in
general, labelled clearly:

- A **3-phase generator** (permanent-magnet alternator topology) is belted
  to the flywheel. User cadence → flywheel RPM → generator RPM → 3-phase
  AC output.
- The generator output is rectified to a DC bus that powers the electronics.
- "Eddy current resistance" in this context is the braking torque the user
  feels as a reaction to the **electrical load** placed on the generator.
  Loading the stator windings induces currents that produce an opposing
  magnetic field on the rotor — those **are** eddy currents in the
  electromagnetic sense.
- The lower board modulates this load (most commonly via a PWM-switched
  dump resistor) to set the resistance level demanded over CSAFE.

**This hypothesis is plausible and consistent with the Precor quote, but
the exact circuit topology is [UNKNOWN] without the service manual.** In
particular, I do not know whether Precor uses:

- a simple PWM-switched dump resistor,
- an active rectifier with regenerative load control,
- a hybrid where some of the generator's output really does power the
  electronics while the remainder is dumped,
- or some other topology Precor prefers.

All of these would appear identical from the CSAFE layer's perspective —
the console just sends `SETGEAR` / `SETPOWER` and the lower board figures
out the rest.

---

## 3. Resistance and power system — AMT

**[VERIFIED]** a full "AMT 885 / 835 / 833 Service Manual (A9)" exists and
is publicly indexed (Scribd, Elektrotanya, ManualsLib — see §7). I have
not read it from this sandbox.

**[INFERRED]** the AMT uses the same self-generating architecture as the
RBK — a generator + eddy-current-style electrical-load brake — because:

- The AMT 835 wakes the console up only after motion, like the RBK.
- Both machines are in the same Precor product family and share the P80
  console and CSAFE command surface.
- The product line is marketed as "self-powered" wherever a wall outlet
  isn't listed.

What differs on the AMT, and what I **do not** have authoritative sources
for:

- **Stride length sensor.** The AMT's defining feature is dynamic stride
  length. The lower board must measure it somehow to compute distance.
  **[UNKNOWN]** whether this is a linear potentiometer, a rotary encoder,
  an optical sensor, or something else.
- **Ramp / angle adjustment.** Some AMT models have a powered ramp motor
  that changes the linkage geometry. **[UNKNOWN]** which of your specific
  units (and which firmware revisions) have this.
- **Emergency-stop lanyard.** Common on striding equipment, usually a
  reed switch or microswitch hard-wired into the safety interlock.
  **[UNKNOWN]** whether the lanyard goes to the lower board directly or
  through the console on the AMT 835.

Get the service manual before you make assumptions about any of these.

---

## 4. P80 console

**[VERIFIED]** from the P80 service manual snippets surfaced in search
results [p80]:

- **CPU/SoC**: TI OMAP (ARM-based) applications processor.
- **Display**: 15-inch HD touchscreen.
- **Connectivity**: Bluetooth and built-in Wi-Fi.
- Early P80 revisions shipped with 256 KB memory (context: likely referring
  to a specific buffer or EEPROM, not system RAM — the snippet was terse).

**[INFERRED]** it boots Linux on internal flash. This is consistent with
OMAP-family devices of that era and with community reports of the P80
dropping to a busybox shell in diagnostic mode, but I did not verify it
from an authoritative Precor document.

**[INFERRED]** the P80 is the CSAFE **master** on the internal bus between
console and lower board, and exposes the lower board's CSAFE port to
external devices via a pass-through. This is consistent with CSAFE's
master/slave architecture and the observable RJ-45 on the machine frame.

The bottom line, which matches what you said: **yes, the P80 is a computer
with a UI and a hard-key matrix sitting on top of a CSAFE master**. When
you remove it, you need to replace the UI (tablet + RN app), the hard-key
matrix (MCU → USB HID or serial to the Pi), and take over the CSAFE
master role (already done by `csafe-server`).

---

## 5. Block diagram (hypothesis level)

This diagram is **[INFERRED]** from §2–§4. Treat it as a working mental
model, not as a reproduction of Precor's schematic.

```
        user torque                         [VERIFIED: 3-phase gen
             │                               + eddy-current brake,
             ▼                               self-powered]
     flywheel + belt
             │
             ▼
  ┌──────────────────────┐
  │  3-phase generator   │──── 3-phase AC ───▶  [INFERRED: rectifier
  │  (PMG, belted)       │                       + DC bus + buck regs
  └──────────────────────┘                       + PWM load-dump brake]
                                                    │
                                                    ▼
                              ┌─────────────────────────────────────┐
                              │    LOWER I/O BOARD  (the brain)     │
                              │  - runs resistance control loop      │
                              │  - reads cadence / speed / HR        │
                              │  - drives AMT ramp motor if present  │
                              │  - CSAFE slave on RJ-45              │
                              └──────────────────┬──────────────────┘
                                                 │  RS-232 9600 8N1
                                                 │  [VERIFIED: CSAFE]
                                                 ▼
                                     ┌─────────────────────┐
                                     │  P80 console or     │
                                     │  csafe-server (Pi)  │
                                     └─────────────────────┘
```

---

## 6. What this means for going headless

Independent of the schematic uncertainty, the CSAFE interface abstracts all
of it away. From `csafe-server`'s point of view:

- `SETGEAR` / `SETPOWER` → resistance
- `GETSPEED` / `GETCADENCE` / `GETPOWER` → user input
- `GETHRCUR` → heart rate (contact pads or wireless strap)

…and whether the brake is a dump resistor or a full regenerative stage
doesn't change how we talk to it.

The things that **do** require the service manual before cutting:

1. Pinout of the internal cable between the lower board and the P80 (so
   you can terminate it cleanly without leaving the lower board asking
   "where's my master?" — if our keepalive heartbeat isn't enough).
2. Pinout of the hard-key matrix inside the P80 (so you can land it on a
   microcontroller).
3. Whether the emergency-stop safety path passes through the console on
   the AMT (critical for safety).

Do not guess any of those from me — get them from the service manual.

---

## 7. Authoritative sources

Read these yourself before making irreversible changes to the machines.

- **CSAFE overview** — Wikipedia, *Communications Specification for Fitness
  Equipment* — [csafe-wiki].
- **CSAFE spec PDF** (FitLinxx original) — widely referenced; one public
  host of the PDF is timkha.com/work/precor/cardiotheater/media/csaf.pdf
  (I could not fetch it from this sandbox).
- **Precor RBK 835 product spec sheet** (the quote used above) —
  [precor-rbk835-spec].
- **Precor EFX 885/835/825 Service Manual** (doc 20039-166) — gympart.com
  hosts it; Precor's customer service (1-800-786-8404) is the primary
  source.
- **Precor AMT 885/835/833 Service Manual (A9)** — found on Scribd,
  Elektrotanya, and ManualsLib.
- **Precor P80 Service Manual** — multiple public mirrors; also available
  from Precor directly.
- **Precor owner / service manuals index** —
  https://www.precor.com/en-us/customer-service/owners-manuals.

[csafe-wiki]: https://en.wikipedia.org/wiki/Communications_Specification_for_Fitness_Equipment
[precor-rbk835-spec]: https://static.precor.com/precor-at-home/legacy/SS_RBK_835_NA_8.5x11_060221.pdf
[p80]: https://www.manualslib.com/manual/976611/Precor-P80.html

---

## 8. Things I got wrong in earlier drafts and corrected here

So you can spot-check me:

- I previously stated specific numbers for DC bus voltage (~30–70 V) and
  a specific MCU family (STM32/PIC) on the lower board. Those were
  engineering guesses presented with too much confidence; I have removed
  them. They belong in the "[UNKNOWN] — measure it" column.
- I previously drew the brake as a "MOSFET + dump resistor" with
  conviction. That is a common topology for this class of machine, but
  Precor's exact implementation is [UNKNOWN] from public sources, so it
  is now marked as such.
- I previously called the P80 keyboard "a matrix ribbon to the P80 board"
  without citation. I have not verified that on the P80 service manual;
  it is [INFERRED] and you should verify before rewiring.

If you spot any remaining unsourced claims, flag them — I'd rather rip
them out than leave false confidence in the repo.
