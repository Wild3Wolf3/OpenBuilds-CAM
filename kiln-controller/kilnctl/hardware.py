"""Thermocouple amplifiers, relay outputs and a simulated kiln.

Real hardware uses only Debian-packaged libraries (python3-spidev,
python3-gpiozero) so the image needs no pip installs.
"""
import logging
import random

log = logging.getLogger(__name__)


class SensorError(Exception):
    pass


# ---------------------------------------------------------------------------
# Thermocouple amplifiers
# ---------------------------------------------------------------------------

class MAX31856:
    """Adafruit #3263 style board on SPI. Supports every thermocouple type."""

    TC_TYPES = {"B": 0, "E": 1, "J": 2, "K": 3, "N": 4, "R": 5, "S": 6, "T": 7}
    FAULTS = {
        0x01: "thermocouple open circuit",
        0x02: "over/under voltage on thermocouple input",
        0x04: "thermocouple temperature low",
        0x08: "thermocouple temperature high",
        0x10: "cold junction low",
        0x20: "cold junction high",
        0x40: "thermocouple out of range",
        0x80: "cold junction out of range",
    }

    def __init__(self, bus, device, tc_type="K", mains_hz=60):
        import spidev
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = 500000
        self.spi.mode = 1
        # CR0: auto-convert, open-circuit detection, mains filter
        cr0 = 0x80 | 0x10 | (0x01 if mains_hz == 50 else 0x00)
        # CR1: average 4 samples, thermocouple type
        cr1 = (0x02 << 4) | self.TC_TYPES[tc_type.upper()]
        self._write(0x00, cr0)
        self._write(0x01, cr1)
        self._write(0x02, 0x00)  # unmask all faults

    def _write(self, reg, value):
        self.spi.xfer2([reg | 0x80, value])

    def _read(self, reg, n):
        return self.spi.xfer2([reg] + [0] * n)[1:]

    def read(self):
        fault = self._read(0x0F, 1)[0]
        if fault:
            names = [msg for bit, msg in self.FAULTS.items() if fault & bit]
            raise SensorError(", ".join(names))
        b = self._read(0x0C, 3)
        raw = (b[0] << 16) | (b[1] << 8) | b[2]
        if raw & 0x800000:
            raw -= 1 << 24
        return (raw >> 5) * 0.0078125

    def cold_junction(self):
        b = self._read(0x0A, 2)
        raw = (b[0] << 8) | b[1]
        if raw & 0x8000:
            raw -= 1 << 16
        return (raw >> 2) * 0.015625


class MAX31855:
    """Older K-type only amplifier (Adafruit #269)."""

    def __init__(self, bus, device, **_):
        import spidev
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = 500000
        self.spi.mode = 0

    def read(self):
        b = self.spi.readbytes(4)
        v = (b[0] << 24) | (b[1] << 16) | (b[2] << 8) | b[3]
        if v & 0x10000:
            if v & 0x1:
                raise SensorError("thermocouple open circuit")
            if v & 0x2:
                raise SensorError("thermocouple shorted to GND")
            if v & 0x4:
                raise SensorError("thermocouple shorted to VCC")
            raise SensorError("thermocouple fault")
        raw = v >> 18
        if raw & 0x2000:
            raw -= 1 << 14
        return raw * 0.25


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

class GPIOOutput:
    def __init__(self, pin, active_high=True):
        from gpiozero import DigitalOutputDevice
        self.dev = DigitalOutputDevice(pin, active_high=active_high, initial_value=False)

    def on(self):
        self.dev.on()

    def off(self):
        self.dev.off()

    @property
    def is_on(self):
        return bool(self.dev.value)


class NullOutput:
    def __init__(self, *_, **__):
        self.is_on = False

    def on(self):
        self.is_on = True

    def off(self):
        self.is_on = False


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

class SimulatedKiln:
    """Lumped thermal model of a ~10 kW electric kiln.

    dT/dt = (P * duty - k * (T - ambient)) / C, with first-order
    thermocouple lag. Full power tops out around 1400 C.
    """

    def __init__(self, watts=10000, ambient=21.0):
        self.ambient = ambient
        self.watts = watts
        self.capacity = 60000.0          # J/K
        self.loss = watts / 1380.0       # W/K
        self.kiln_temp = ambient
        self.tc_temp = ambient
        self.tc_lag = 20.0               # seconds

    def advance(self, dt, duty):
        steps = max(1, int(dt))
        h = dt / steps
        for _ in range(steps):
            power = self.watts * duty - self.loss * (self.kiln_temp - self.ambient)
            self.kiln_temp += power / self.capacity * h
            self.tc_temp += (self.kiln_temp - self.tc_temp) * min(1.0, h / self.tc_lag)

    def read(self):
        return self.tc_temp + random.uniform(-0.15, 0.15)


class Hardware:
    """Everything the controller touches, real or simulated."""

    def __init__(self, cfg):
        self.simulated = bool(cfg["simulate"]) or cfg["sensor"] == "simulated"
        self.sim = None
        self.estop_callback = None
        self._buttons = []
        if self.simulated:
            log.warning("running in SIMULATION mode - no hardware is driven")
            self.sim = SimulatedKiln(watts=cfg["element_watts"])
            self.sensor = self.sim
            self.heater = NullOutput()
            self.contactor = NullOutput()
            self.buzzer = NullOutput()
            return

        sensor_cls = {"max31856": MAX31856, "max31855": MAX31855}[cfg["sensor"]]
        self.sensor = sensor_cls(cfg["spi_bus"], cfg["spi_device"],
                                 tc_type=cfg["thermocouple_type"], mains_hz=cfg["mains_hz"])
        self.heater = GPIOOutput(cfg["heater_pin"], cfg["heater_active_high"])
        self.contactor = GPIOOutput(cfg["contactor_pin"], cfg["contactor_active_high"])
        self.buzzer = GPIOOutput(cfg["buzzer_pin"]) if cfg["buzzer_pin"] is not None else NullOutput()
        if cfg["estop_pin"] is not None:
            from gpiozero import Button
            button = Button(cfg["estop_pin"], pull_up=True, bounce_time=0.05)
            button.when_pressed = self._on_estop
            self._buttons.append(button)

    def _on_estop(self):
        # gpiozero calls this from its own thread; kill power immediately.
        self.heater.off()
        self.contactor.off()
        if self.estop_callback:
            self.estop_callback()

    def advance(self, dt, duty):
        if self.sim:
            self.sim.advance(dt, duty)

    def read_temp(self, offset=0.0):
        return self.sensor.read() + offset

    def all_off(self):
        self.heater.off()
        self.contactor.off()

