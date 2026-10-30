# Parts list

Prices are rough USD street prices (late 2026) to help with budgeting. Brands are examples, not
requirements. **Size every mains-side part for your kiln's nameplate current.** Look for the amps on
the kiln's data plate, or work it out as watts ÷ volts.

> ⚠️ Kilns run on 208–240 V at 15–60 A. A wiring mistake can kill you or start a fire. If you're not
> qualified to do mains wiring, have a licensed electrician build or inspect the power side. Follow
> your local electrical code.

## A. Controller electronics (required)

| # | Part | Qty | Notes | ≈ Price |
|---|------|-----|-------|---------|
| 1 | **Raspberry Pi 4 Model B, 2 GB** | 1 | Recommended because its hardware JPEG encoder keeps the camera cheap on CPU. A Pi 5 (2 GB) also works. A Pi Zero 2 W works without the camera. | $45 |
| 2 | microSD card, 32 GB, **high-endurance** | 1 | e.g. SanDisk High Endurance or Samsung PRO Endurance. It survives constant logging. | $10 |
| 3 | 5 V 3 A power supply | 1 | Official Pi USB-C PSU, or a DIN-rail Mean Well **HDR-30-5** inside the enclosure | $10–15 |
| 4 | **Adafruit MAX31856** universal thermocouple amplifier (#3263) | 1 | Reads K, N, S, R, B and other types, detects an open thermocouple, and has a 50/60 Hz noise filter. The older MAX31855 (#269, K-type only) is also supported. | $18 |
| 5 | **Kiln thermocouple, Type K, 8 AWG**, with a ceramic protection tube | 1 | Rated ≥ 1260 °C / 2300 °F. For frequent cone 8–10 firings, use **Type N** (lasts longer) or **Type S** (platinum, $150+). | $25–45 |
| 6 | Type-K thermocouple extension wire, 20 AWG, fibreglass-insulated | 3 m | Use the extension wire that matches your thermocouple type. Ordinary copper wire gives wrong readings. | $15 |
| 7 | Thermocouple mini connector pair (e.g. Omega SMPW-K-MF) | 1 | Lets you swap the thermocouple without opening the box | $8 |
| 8 | Logic-level transistor or small MOSFET + 1 kΩ resistor (e.g. 2N2222/BC337) | 1 | Drives the SSR from 5 V. Optional for SSRs that draw < 10 mA on their input. | $1 |
| 9 | 1-channel relay module, 5 V, optocoupled | 1 | Switches the safety contactor's coil. Many modules are active-low, so set that in Settings. | $6 |
| 10 | Jumper wires, standoffs, ferrules, heat-shrink | — | | $10 |

## B. Power switching (required – size to your kiln)

| # | Part | Qty | Notes | ≈ Price |
|---|------|-----|-------|---------|
| 11 | **Solid-state relay, zero-cross, 3–32 VDC input, 240 VAC output** | 1 per element circuit | Rate it at **≥ 1.5× the circuit's current**. Use a genuine Crydom/Sensata (D2440, D2450, D2475), Opto22 or Carlo Gavazzi part. Avoid cheap "Fotek" clones: they are often counterfeit and badly over-rated. | $40–80 each |
| 12 | SSR heatsink (≤ 0.5 °C/W for 40 A) + thermal paste | 1 per SSR | SSRs lose about 1.5 W per amp as heat. Without a heatsink they fail closed, which leaves the heater stuck ON. | $15–25 |
| 13 | **2-pole definite-purpose contactor**, contacts ≥ kiln amps, coil = your mains voltage (120 or 240 VAC) | 1 | This is the independent safety disconnect. It breaks **both** hot legs and opens on E-stop, on any fault, and whenever the Pi is off. | $20–35 |
| 14 | 22 mm **latching mushroom E-stop**, 1 NC + 1 NO contact block | 1 | The NC contact is wired in series with the contactor coil, so it works even if the Pi is dead. The NO contact goes to GPIO 17 so the software logs it. | $10–15 |
| 15 | **Independent over-temperature limit**: a second controller with its own thermocouple and an alarm relay (e.g. Auber SYL-2352 or Inkbird ITC-106 with a K input) | 1 | Strongly recommended. Its alarm relay sits in series with the contactor coil and cuts power above a fixed limit even if the Pi software fails. | $35–80 |
| 16 | Fuse holder + 2 A fuse for the control circuit | 1 | Protects the Pi PSU and contactor coil wiring | $8 |
| 17 | Power distribution blocks / DIN terminal blocks rated for kiln current | set | e.g. 6 AWG / 65 A blocks for the mains side | $20–30 |
| 18 | Copper wire for the mains path: **8 AWG (≤ 40 A)** or **6 AWG (≤ 55 A)**, THHN/MTW, 90 °C rated; 18 AWG for the coil circuit | as needed | Match your breaker and local code | $20–40 |
| 19 | Kiln supply cord + plug (e.g. NEMA 6-50P, SOOW 6/3) and cord grips | 1 | Often you can reuse the kiln's existing cord | $25–60 |

## C. Enclosure

| # | Part | Qty | Notes | ≈ Price |
|---|------|-----|-------|---------|
| 20 | Steel electrical enclosure, about 12×10×6 in (300×250×150 mm), with a back plate and DIN rail | 1 | Mount it **beside** the kiln, not on it. Heat kills electronics. | $45–70 |
| 21 | 80 mm fan + filter grille (5 V or 12 V) | 1 | Removes SSR heat | $10 |
| 22 | Ground lug and bonding jumper | 1 | Bond the enclosure and kiln shell to ground | $5 |

## D. Camera

| # | Part | Qty | Notes | ≈ Price |
|---|------|-----|-------|---------|
| 23 | **Raspberry Pi Camera Module 3** (Standard or Wide) | 1 | Autofocus works well through a peephole. The NoIR version sees more of the glow. Any UVC USB webcam also works (install `python3-opencv`). | $25–35 |
| 24 | Long CSI ribbon cable, 500 mm–1 m | 1 | A Pi 5 needs the 22-pin to 15-pin "mini" cable | $5–8 |
| 25 | Camera mount / small project box, and a **welding-glass filter (shade 5–8)** or ND filter | 1 | Aim at a peephole or cone pack from **≥ 30 cm away**. The filter stops the glow from washing out the image above about 900 °C. Never put the camera in the peephole. | $10–20 |

## E. Optional touchscreen

The kiln UI runs full-screen on the Pi itself, with big touch buttons, a pinned EMERGENCY STOP bar
and an on-screen keyboard. Enable it with `KILN_TOUCHSCREEN=1` when building the image, or run
`sudo ./install.sh --touchscreen`.

| # | Part | Qty | Notes | ≈ Price |
|---|------|-----|-------|---------|
| 26 | **Raspberry Pi Touch Display 2 (7", 720×1280)** *(recommended)*, or the original official 7" Touch Display (800×480), or a 5"/7" capacitive HDMI touchscreen (e.g. Waveshare, 800×480 or 1024×600) | 1 | The official displays connect by DSI ribbon, so the camera keeps the CSI port. HDMI screens also need a USB cable for touch. | $45–65 |
| 27 | Display mounting: a panel-mount bezel or case that fits a cut-out in the enclosure door, or a separate small case on an arm | 1 | Keep the screen away from kiln heat. The Pi and display are rated to about 50 °C. | $10–25 |
| 28 | Longer DSI cable (200–500 mm), if the display isn't directly on the Pi | 1 | A Pi 5 needs the "standard-to-mini" DSI cable | $5–8 |
| 29 | Bigger power supply: **5 V 3 A** minimum for a Pi 4 + display, or the **27 W (5 V 5 A) USB-C PSU** for a Pi 5 | — | Official displays are powered from the Pi's 5 V header pins (use pin 4 if pin 2 already feeds the SSR driver) | +$5 |

Adds **≈ $60–100** to the build.

## F. Optional extras

| Part | Why | ≈ Price |
|------|-----|---------|
| 5 V active buzzer + transistor (GPIO 18) | Local audible alarm on a fault | $3 |
| DS3231 RTC module (Pi 4), or the RTC battery for a Pi 5 | Correct timestamps without internet | $5 |
| UPS HAT / mini UPS for the Pi | Rides through short brownouts and keeps logging | $30–45 |
| SCT-013 current clamp + ADS1115 ADC | Measures real element current to catch a failing element early | $15 |
| Lid/door microswitch | Lets the software block heating while the lid is open | $5 |

## Typical total

* Controller + switching + enclosure (one 40 A circuit): **≈ $300–450**
* Camera: **+ $40–60**
* Independent over-temperature limit: **+ $35–80** (recommended)
* Touchscreen: **+ $60–100** (optional)
