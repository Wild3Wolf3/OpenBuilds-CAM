"""Configuration: defaults merged with /var/lib/kiln/config.json.

All temperatures are stored internally in degrees Celsius. The web UI
converts to the display unit chosen in settings.
"""
import copy
import hashlib
import hmac
import json
import os
import secrets

DATA_DIR = os.environ.get("KILN_DATA_DIR", "/var/lib/kiln")

DEFAULTS = {
    # --- display -----------------------------------------------------------
    "units": "F",                    # "F" or "C" (display only)
    "kiln_name": "Kiln",

    # --- hardware ----------------------------------------------------------
    "simulate": False,               # True = no hardware, simulated kiln
    "sim_speed": 1.0,                # simulation time multiplier (demo only)
    "sensor": "max31856",            # "max31856" | "max31855" | "simulated"
    "thermocouple_type": "K",        # MAX31856 only: B E J K N R S T
    "spi_bus": 0,
    "spi_device": 0,                 # CE0 = GPIO8
    "mains_hz": 60,                  # noise filter for MAX31856 (50 or 60)
    "tc_offset": 0.0,                # calibration offset, deg C
    "heater_pin": 23,                # SSR control (BCM numbering)
    "heater_active_high": True,
    "contactor_pin": 24,             # safety contactor relay, closed only while firing
    "contactor_active_high": True,
    "estop_pin": 17,                 # physical E-stop push button to GND (None = unused)
    "buzzer_pin": None,              # optional alarm buzzer

    # --- control -----------------------------------------------------------
    "cycle_seconds": 2.0,            # SSR time-proportioning window
    "pid_kp": 0.04,                  # duty per deg C of error
    "pid_ki": 0.00006,               # duty per (deg C * s)
    "pid_kd": 2.0,                   # duty per (deg C / s)
    "catch_up": True,                # pause schedule clock while kiln lags
    "catch_up_delta": 8.0,           # deg C lag that triggers catch-up

    # --- safety ------------------------------------------------------------
    "max_temp": 1300.0,              # absolute limit, deg C -> emergency stop
    "overshoot_abort": 40.0,         # abort if temp > setpoint + this
    "sensor_fault_limit": 5,         # consecutive bad reads before abort
    "stall_minutes": 30,             # at ~full power this long ...
    "stall_min_rise": 5.0,           # ... must gain at least this many deg C
    "runaway_minutes": 10,           # heater off this long ...
    "runaway_rise": 20.0,            # ... yet temp rose this much = stuck SSR
    "max_firing_hours": 36,          # hard cap on any firing
    "auto_resume_minutes": 20,       # resume after power loss if outage shorter (0 = never)
    "safe_open_temp": 50.0,          # notify when cooled below this after firing

    # --- energy ------------------------------------------------------------
    "element_watts": 10000,
    "price_per_kwh": 0.15,
    "currency": "$",

    # --- camera ------------------------------------------------------------
    "camera_enabled": True,
    "camera_resolution": [1280, 720],
    "camera_fps": 10,
    "timelapse_minutes": 5,          # snapshot interval while firing (0 = off)

    # --- notifications -----------------------------------------------------
    "notify_url": "",                # e.g. https://ntfy.sh/my-kiln-topic

    # --- web ---------------------------------------------------------------
    "http_port": 80,
    "password_hash": "",             # empty = no login required
    "secret": "",                    # cookie signing key (generated)
}

# Keys the web UI may change. Everything else is file-only.
EDITABLE = set(DEFAULTS) - {"secret", "password_hash"}


class Config:
    def __init__(self, data_dir=DATA_DIR):
        self.data_dir = data_dir
        self.path = os.path.join(data_dir, "config.json")
        self.values = copy.deepcopy(DEFAULTS)
        os.makedirs(data_dir, exist_ok=True)
        if os.path.exists(self.path):
            with open(self.path) as f:
                self.values.update(json.load(f))
        if os.environ.get("KILN_SIMULATE") == "1":
            self.values["simulate"] = True
        if not self.values["secret"]:
            self.values["secret"] = secrets.token_hex(32)
            self.save()

    def __getitem__(self, key):
        return self.values[key]

    def get(self, key, default=None):
        return self.values.get(key, default)

    def update(self, changes):
        unknown = set(changes) - EDITABLE
        if unknown:
            raise ValueError("unknown settings: " + ", ".join(sorted(unknown)))
        for key, value in changes.items():
            default = DEFAULTS[key]
            if isinstance(default, bool):
                value = bool(value)
            elif isinstance(default, float):
                value = float(value)
            elif isinstance(default, int) and value is not None:
                value = int(value)
            self.values[key] = value
        if self.values["units"] not in ("C", "F"):
            raise ValueError("units must be C or F")
        self.save()

    def public(self):
        """Settings as shown to the UI (no secrets)."""
        out = {k: v for k, v in self.values.items() if k not in ("secret", "password_hash")}
        out["password_set"] = bool(self.values["password_hash"])
        return out

    def set_password(self, password):
        if password:
            salt = secrets.token_hex(16)
            digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
            self.values["password_hash"] = salt + "$" + digest.hex()
        else:
            self.values["password_hash"] = ""
        self.save()

    def check_password(self, password):
        stored = self.values["password_hash"]
        if not stored:
            return True
        salt, digest = stored.split("$", 1)
        test = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
        return hmac.compare_digest(test.hex(), digest)

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.values, f, indent=2)
        os.replace(tmp, self.path)
