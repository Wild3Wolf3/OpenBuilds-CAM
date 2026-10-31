# Additional ideas

## Already built in (beyond the basic request)

| Feature | Why it matters |
|---|---|
| **Safety contactor** on its own GPIO, closed only while firing | A shorted SSR (the usual way they fail) can't keep heating the kiln |
| Physical **E-stop button** input, plus a software E-stop | Works from the shed without a phone |
| **Stall detection** (full power but no temperature rise) | Catches burnt-out elements, a failed relay or a thermocouple that fell out |
| **Stuck-relay detection** (temperature rises while the heater is off) | Catches a welded SSR |
| Over-temperature, overshoot, thermocouple-fault and max-duration aborts | Several independent ways to stop a runaway |
| **systemd watchdog + Pi hardware watchdog** | If the software or OS hangs, it's restarted and the outputs drop to off |
| **Power-loss resume** | After a short outage the firing continues where the kiln actually is. Longer outages are logged as interrupted. |
| **Catch-up** (pauses the schedule while the kiln lags) | The program never runs ahead of the kiln, so hold times stay real |
| "As fast as possible" steps (time = 0:00) and **controlled-cooling** steps | Covers glass annealing and slow-cool glazes |
| **Enter a ramp as a time or as a rate** (°/hr) | Potters usually think in rates. Each field fills in the other. |
| **Push notifications** (ntfy.sh) on start, finish, faults and "cool enough to open" | No need to babysit the dashboard |
| **Time-lapse snapshots** saved with each firing log | Watch cone packs bend afterwards |
| **Energy and cost** per firing | Helps with pricing your work |
| Firing **history** with charts and CSV export | Compare firings and diagnose problems |
| Profile **import/export** (JSON) | Share schedules with other users |
| **Wi-Fi setup hotspot** + Wi-Fi page in the UI | Works with no keyboard or monitor |
| Optional **interface passcode** with touchscreen auto-lock | Stops anyone on the Wi-Fi, or walking past, from using the kiln |
| Optional **firing lock PIN** for changes to a running firing (never for E-stop) | Nobody can stop or skip a firing by accident or without permission |
| **Simulation mode** | Try profiles and learn the UI with no hardware |
| Optional **touchscreen kiosk** with on-screen keyboard and pinned E-stop bar | Control the kiln at the kiln, no phone needed |

## Suggested next steps

1. **Independent hardware over-temperature limit.** It's in the parts list. It's the single most
   important upgrade, because it doesn't trust the Pi at all.
2. **Lid/door switch** on a GPIO. Block heating with the lid open (it's also an element-contact
   safety issue on top-loaders) and pause the program when the lid opens.
3. **Element current monitoring** (SCT-013 clamp + ADS1115). Track element resistance over time and
   warn before an element fails mid-firing.
4. **PID autotune.** Run a relay-feedback test once to find good gains for your particular kiln.
5. **Zone control** for large kilns: two or three thermocouples, each with its own SSR, to even out
   top/bottom temperatures.
6. **Home Assistant / MQTT** publishing. `GET /api/status` is already JSON, so this is a small adapter.
7. **Cone-based programming**: pick "cone 6, medium speed" and generate the steps from Orton cone
   tables. Show "equivalent cone" (heat-work) live during the firing.
8. **Delayed start**: begin at a set time, for example off-peak electricity at night.
9. **Firing notes and photos** attached to each history entry: glaze, clay body, results.
10. **Screen dimming** for the touchscreen: turn the backlight down when idle, and wake it on touch or on an alarm.
11. **Off-site access** through Tailscale or a Cloudflare Tunnel, rather than port-forwarding.
    Don't expose the kiln directly to the internet.
12. **Thermocouple drift tracking**: log witness-cone results and suggest an offset correction.
