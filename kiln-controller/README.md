# Kiln Controller for Raspberry Pi

A web-enabled controller for electric kilns (ceramics, glass, metal clay), with Wi-Fi, a live camera,
step programs of up to 35 steps, saved profiles and layered safety shut-offs. It runs on a Raspberry Pi
with a MAX31856 thermocouple amplifier, a solid-state relay and a safety contactor. It was inspired by
the Instructables
"[Build a Web-Enabled High Temperature Kiln Controller](https://www.instructables.com/Build-a-Web-Enabled-High-Temperature-Kiln-Controll/)".

> ⚠️ **Safety.** This software controls a device that reaches 1300 °C on a high-current mains circuit.
> Use it with an independent hardware over-temperature limit and a hard-wired E-stop, as described
> in the [wiring guide](docs/WIRING.md). Never leave a firing unattended for long periods.

## Features

* **Dashboard**: big live temperature readout, setpoint, heater power, current step, time
  remaining, energy and cost, a live planned-vs-actual chart, and the camera stream.
* **Controls**: Start, Hold/Resume, Skip step, Stop, a large **EMERGENCY STOP**, and a physical E-stop input.
* **Step programs**: each step is *target temperature + time to get there + optional hold*. Step 1
  starts from whatever temperature the kiln is at. **+ Add step** adds rows up to **35**. You can
  type a ramp *time* or a *rate* (°/hr) and the other fills itself in. A time of 0:00 means "as fast
  as possible". A lower target than the previous step means a controlled cool.
* **Profiles**: 12 built-in presets (bisque, low/mid/high-fire glaze, slow cool, glass full/tack fuse,
  slump, silver clay, drying, test). Save your own, use *Save as new* to customise a preset, and
  import/export profiles as JSON.
* **Live temperature feed** over a WebSocket, plus `GET /api/status` (JSON) for Home Assistant and other tools.
* **Camera**: Pi Camera (Picamera2) or a USB webcam, MJPEG live view, and time-lapse snapshots saved with each firing.
* **History**: every firing is logged with a chart, snapshots, CSV download, peak temperature, kWh and cost.
* **Safety**: a contactor cut-off, aborts on over-temperature, overshoot, thermocouple faults, stalls
  and stuck relays, a maximum firing time, the systemd and hardware watchdogs, and power-loss
  resume. See [docs/IDEAS.md](docs/IDEAS.md).
* **Wi-Fi**: if the Pi can't find a network at boot it starts a `Kiln-Setup` hotspot. Join it and
  pick your Wi-Fi in Settings. The UI is reachable at **http://kiln.local** (mDNS).
* **Notifications** through [ntfy.sh](https://ntfy.sh) (free phone push): firing started, finished,
  alarm, and "cool enough to open".
* Optional **password login**, °F/°C display, and a **simulation mode** for trying it without hardware.

## Documentation

* [Full parts list](docs/PARTS_LIST.md)
* [Wiring and first power-up checklist](docs/WIRING.md)
* [Built-in extras and suggested ideas](docs/IDEAS.md)

## Option 1: Flash the ready-made image

The image is Raspberry Pi OS Lite (64-bit) with everything pre-installed. It's built by GitHub
Actions with the official [pi-gen](https://github.com/RPi-Distro/pi-gen) tool.

1. Get the image: **Actions → Kiln controller → Run workflow** and download the
   `kiln-controller-image` artifact, or push a tag such as `kiln-v1.0.0` to have it attached to a
   GitHub Release.
2. Flash `kiln-controller.img.xz` to a microSD card with **Raspberry Pi Imager** (*Choose OS → Use
   custom*) or balenaEtcher. When Imager offers OS customisation, choose **No**: the image has its own
   settings.
3. Boot the Pi. If you didn't bake in Wi-Fi, wait about 2 minutes, then join the Wi-Fi network
   **`Kiln-Setup`** (password `kilnsetup`). Browse to **http://10.42.0.1**, open Settings → Wi-Fi,
   choose your network, then reconnect your phone to your normal Wi-Fi.
4. Open **http://kiln.local**. In Settings, set a login password, your units and your kiln's wattage.
5. SSH login: `ssh kiln-admin@kiln.local`. The default password is `kilnadmin` unless you set the
   `KILN_ADMIN_PASSWORD` secret. **Change it** with `passwd`.

Optional repository **secrets** for the image build: `KILN_ADMIN_PASSWORD`, `KILN_WIFI_SSID`,
`KILN_WIFI_PASSWORD`. Optional **variables**: `KILN_WIFI_COUNTRY` (default `US`) and
`KILN_TIMEZONE`. Wi-Fi credentials baked into an image can be read by anyone who has the
image, so don't share an image built with them.

### Building the image yourself

On any Linux machine with Docker (an arm64 host is fastest):

```bash
cd kiln-controller/image
KILN_ADMIN_PASSWORD='choose-one' KILN_WIFI_SSID='MyWiFi' KILN_WIFI_PASSWORD='secret' ./build-image.sh
# → image/build/pi-gen/deploy/*kiln-controller*.img.xz
```

On an x86 host, install `qemu-user-static binfmt-support` first. A build takes 30–90 minutes.

## Option 2: Install on an existing Raspberry Pi OS

```bash
git clone <this repo> && cd <repo>/kiln-controller
sudo ./install.sh
sudo reboot          # first time only, to enable SPI
```

## Try it without hardware

```bash
pip install aiohttp
cd kiln-controller
python3 -m kilnctl --simulate --data-dir ./data --port 8080
# open http://localhost:8080. Set "Simulation speed" in Settings to fast-forward.
```

Tests: `pip install pytest && python3 -m pytest tests`. They include full simulated firings of the
presets, checks that each safety abort trips, and power-loss resume.

## Tuning

The defaults suit a typical 7–11 kW kiln. If the temperature oscillates, lower **Kp**. If it
consistently lags the schedule, raise **Ki** slightly. After a few firings, check witness cones and set
the **thermocouple calibration offset**.

## How it works

```
kilnctl/
  controller.py   schedule clock, PID, SSR time-proportioning, safety checks, logs, resume
  profiles.py     validation (≤ 35 steps), schedule interpolation, profile storage
  hardware.py     MAX31856 / MAX31855 over SPI, GPIO outputs, E-stop input, simulated kiln
  pid.py          PID with anti-windup
  camera.py       Picamera2 / OpenCV MJPEG
  web.py          REST API, WebSocket, camera stream, auth
  wifi.py         nmcli wrapper
  static/         web UI (plain HTML/JS/CSS, no internet needed)
  presets/        built-in profiles (°C, minutes)
system/           systemd units, hotspot script, polkit rule, watchdog
image/            pi-gen stage + build script
```

Every 2 s the controller reads the thermocouple and works out the setpoint from the schedule. The PID
turns that into a duty cycle, and the SSR is switched on for that fraction of the 2 s window. Data
lives in `/var/lib/kiln`: `config.json`, `profiles/`, and `logs/<run>/` (`log.csv`, `meta.json`,
`snapshots/`).

### API summary

| Method | Path | |
|---|---|---|
| GET | `/api/status` | live status (also pushed on `/ws`) |
| POST | `/api/firing/start` | `{"profile_id": "glaze-cone-6"}` or `{"profile": {...}}` |
| POST | `/api/firing/stop` · `estop` · `hold` · `resume` · `skip` · `ack` | |
| GET/POST | `/api/profiles` | list / create |
| PUT/DELETE | `/api/profiles/{id}` | update / delete |
| GET | `/api/history`, `/api/history/{run}`, `/api/history/{run}/log.csv` | |
| GET/PUT | `/api/settings` | |
| GET | `/camera/stream.mjpg`, `/camera/snapshot.jpg` | |

Profile JSON (temperatures in °C, times in minutes):

```json
{"name": "My bisque", "steps": [
  {"target": 93,  "minutes": 60,  "hold": 60},
  {"target": 999, "minutes": 420, "hold": 10}
]}
```
