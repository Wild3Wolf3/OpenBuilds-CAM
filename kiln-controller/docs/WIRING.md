# Wiring

> ⚠️ Mains voltage. De-energise the kiln circuit at the breaker before you work on it. Have a
> qualified electrician check the power wiring before the first firing.

## Raspberry Pi GPIO (BCM numbering, defaults in Settings → Hardware)

| Function | GPIO | Header pin | Connects to |
|---|---|---|---|
| 3.3 V | — | 1 | MAX31856 **VIN** |
| 5 V | — | 2 | SSR driver / relay module **VCC** |
| GND | — | 6 | MAX31856 **GND**, relay module **GND**, SSR input − |
| SPI MOSI | 10 | 19 | MAX31856 **SDI** |
| SPI MISO | 9 | 21 | MAX31856 **SDO** |
| SPI SCLK | 11 | 23 | MAX31856 **SCK** |
| SPI CE0 | 8 | 24 | MAX31856 **CS** |
| Heater SSR | **23** | 16 | SSR input + (directly, or through the transistor driver below) |
| Safety contactor relay | **24** | 18 | Relay module **IN** |
| E-stop sense | **17** | 11 | E-stop NO contact → GND (pin 9) |
| Buzzer (optional) | 18 | 12 | Buzzer driver transistor |

Thermocouple → MAX31856 screw terminals. Type K: **yellow = +**, **red = −** (US colour code).
Keep thermocouple wires away from the mains wiring, and twist the pair.

## Low-voltage side

```
            Raspberry Pi                              MAX31856
         ┌──────────────┐                          ┌──────────┐
  pin 1  │ 3V3          ├──────────────────────────┤ VIN      │      Type-K thermocouple
  pin 19 │ GPIO10 MOSI  ├──────────────────────────┤ SDI   T+ ├────── yellow (+)
  pin 21 │ GPIO9  MISO  ├──────────────────────────┤ SDO   T- ├────── red    (−)
  pin 23 │ GPIO11 SCLK  ├──────────────────────────┤ SCK      │
  pin 24 │ GPIO8  CE0   ├──────────────────────────┤ CS       │
  pin 6  │ GND          ├──────────┬───────────────┤ GND      │
         │              │          │               └──────────┘
  pin 2  │ 5V           ├────┬─────┼────────────────────────────┐
         │              │    │     │                            │
  pin 16 │ GPIO23       ├─1kΩ─┐    │       SSR (3–32 VDC in)    │
         │              │     B    │         ┌───────┐          │
         │              │  NPN C───┼─────────┤ in −  │          │
         │              │     E────┤         │ in +  ├──────────┘
         │              │          │         └───────┘
  pin 18 │ GPIO24       ├──────────┼───── IN   ┐
         │              │          ├───── GND  │ relay module → switches contactor coil
         │              │    └─────┼───── VCC  ┘
  pin 11 │ GPIO17       ├────┐     │
  pin 9  │ GND          ├─┐  └── E-stop NO contact ──┐
         └──────────────┘ └──────────────────────────┘
```

Most 3–32 V SSRs draw only 6–12 mA, so you can usually wire GPIO 23 straight to SSR input + and GND
to input −. The transistor driver is safer for the Pi.

## Mains side (240 V split-phase shown)

```
 L1 ──[ breaker ]──┬──────────── contactor pole 1 ─── SSR ─── elements ───┐
                   │                                                      │
 L2 ──[ breaker ]──┼─┬────────── contactor pole 2 ────────────────────────┘
                   │ │
                   │ │   control circuit (coil = mains voltage)
                   │ │
                   └─┼─[2 A fuse]─[E-stop NC]─[over-temp limit NC]─[relay module NO/COM]─ coil A1
                     └───────────────────────────────────────────────────────────────────── coil A2

 Ground ──── kiln shell ──── enclosure ──── cord ground
```

* The **contactor** breaks both legs. It closes only while the software is firing, while the E-stop
  is released, and while the independent limit is happy. Even if the SSR fails shorted (its common
  failure mode), the contactor still cuts the power.
* Kilns with several element circuits: give each circuit its own SSR (all driven from GPIO 23) and
  run all of them through the contactor, or through one contactor per circuit with the coils in
  parallel.
* Mount each SSR on its heatsink with thermal paste, with the fins vertical and the fan blowing across.

## Thermocouple placement

* Put it through the kiln wall at the height of the ware, with the tip **25–40 mm** inside the kiln.
  Keep it clear of the elements and of shelves.
* Seal around it with kiln cement or fibre so cold air doesn't leak in.
* Fire witness cones on the first few runs and adjust **Settings → Thermocouple calibration offset**
  until the cones and the readout agree.

## First power-up checklist

1. With the mains disconnected, boot the Pi and confirm the dashboard shows room temperature.
2. Warm the thermocouple tip with your hand or a lighter: the reading should go **up**. If it goes
   down, the thermocouple leads are reversed.
3. Run **Test - short 200 C** with the kiln powered. Listen for the contactor click, and watch the
   SSR LED pulse and the temperature rise.
4. Press the E-stop. The contactor should drop out right away, and the UI should show the alarm.
5. Unplug the thermocouple during a test firing. The firing should abort with
   "thermocouple open circuit".
