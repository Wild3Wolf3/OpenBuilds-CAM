"""Firing controller: runs the schedule, drives the SSR, enforces safety."""
import asyncio
import collections
import csv
import json
import logging
import os
import socket
import time

from .hardware import SensorError
from .pid import PID
from .profiles import Schedule, validate

log = logging.getLogger(__name__)

LOG_INTERVAL = 30.0  # seconds of firing time between logged points

IDLE, FIRING, HOLDING, COMPLETE, STOPPED, ERROR = (
    "idle", "firing", "holding", "complete", "stopped", "error")
ACTIVE = (FIRING, HOLDING)


def sd_notify(msg):
    """Tell systemd we're alive (Type=notify + WatchdogSec in the unit)."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(addr)
            s.sendall(msg.encode())
    except OSError:
        pass


class Controller:
    def __init__(self, cfg, hw, notifier=None, camera=None):
        self.cfg = cfg
        self.hw = hw
        self.notifier = notifier
        self.camera = camera
        self.listeners = []
        self.time_scale = max(1.0, float(cfg["sim_speed"])) if hw.simulated else 1.0
        self.log_dir = os.path.join(cfg.data_dir, "logs")
        self.state_path = os.path.join(cfg.data_dir, "run_state.json")
        os.makedirs(self.log_dir, exist_ok=True)

        self.state = IDLE
        self.message = ""
        self.temp = None
        self.sensor_error = ""
        self.bad_reads = 0
        self.duty = 0.0
        self.setpoint = None
        self.catching_up = False
        self.pid = PID(cfg["pid_kp"], cfg["pid_ki"], cfg["pid_kd"])
        self.history = collections.deque()       # (fire_time, temp, duty) for safety windows
        self._reset_run()
        self.safe_open_notified = True
        hw.estop_callback = self._estop_from_thread
        self._loop = None

    def _reset_run(self):
        self.profile = None
        self.schedule = None
        self.run_id = None
        self.sched_time = 0.0       # schedule clock (pauses while catching up / holding)
        self.fire_time = 0.0        # total time since start
        self.energy_j = 0.0
        self.points = []            # [fire_time, temp, setpoint] every LOG_INTERVAL
        self._next_log = 0.0
        self._next_save = 0.0
        self._next_snapshot = 0.0
        self._csv = None

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def start(self, profile):
        if self.state in ACTIVE:
            raise ValueError("a firing is already running")
        profile = {**validate(profile), "id": profile.get("id")}
        if self.temp is None or self.sensor_error:
            raise ValueError("no valid thermocouple reading: " + (self.sensor_error or "waiting for sensor"))
        hottest = max(s["target"] for s in profile["steps"])
        if hottest > self.cfg["max_temp"]:
            raise ValueError("profile exceeds the configured max temperature")
        self._reset_run()
        self.profile = profile
        self.schedule = Schedule(profile, self.temp)
        self.run_id = time.strftime("%Y%m%d-%H%M%S")
        self._open_run_log()
        self.pid.reset()
        self.hw.buzzer.off()
        self.hw.contactor.on()
        self.state = FIRING
        self.message = f"Started {profile['name']}"
        self.safe_open_notified = False
        self._notify("Firing started", f"{profile['name']} from {self.temp:.0f} C")
        self._save_state()
        self._publish()

    def stop(self, reason="Stopped by user"):
        self.hw.all_off()
        if self.state in ACTIVE:
            self._finish(STOPPED, reason)
        self._publish()

    def emergency_stop(self, reason="EMERGENCY STOP"):
        self.hw.all_off()
        if self.state in ACTIVE:
            self._finish(ERROR, reason)
        else:
            self.state, self.message = ERROR, reason
        self._publish()

    def hold(self):
        if self.state == FIRING:
            self.state = HOLDING
            self.message = "Holding at current setpoint"
            self._publish()

    def resume(self):
        if self.state == HOLDING:
            self.state = FIRING
            self.message = "Resumed"
            self._publish()

    def skip_step(self):
        if self.state not in ACTIVE:
            raise ValueError("not firing")
        step = self.schedule.segment_at(self.sched_time).step
        self.sched_time = self.schedule.step_end(step)
        self.message = f"Skipped step {step + 1}"
        self._publish()

    def acknowledge(self):
        """Clear a finished/error state back to idle and silence the alarm."""
        if self.state not in ACTIVE:
            self.hw.buzzer.off()
            self.state = IDLE
            self.message = ""
            self._publish()

    def _estop_from_thread(self):
        if self._loop:
            self._loop.call_soon_threadsafe(self.emergency_stop, "Physical E-stop button pressed")

    # ------------------------------------------------------------------
    # Control loop
    # ------------------------------------------------------------------

    async def run(self):
        self._loop = asyncio.get_running_loop()
        cycle = float(self.cfg["cycle_seconds"])
        self._read_sensor()
        self._try_resume()
        sd_notify("READY=1")
        try:
            while True:
                try:
                    duty = self.tick(cycle)
                except Exception as exc:  # never leave the heater in an unknown state
                    log.exception("control loop failure")
                    duty = 0.0
                    self.emergency_stop(f"Controller fault: {exc}")
                on_time = duty * cycle
                if on_time >= 0.05 and self.state in ACTIVE:
                    self.hw.heater.on()
                    await asyncio.sleep(on_time / self.time_scale)
                self.hw.heater.off()
                await asyncio.sleep(max(0.0, cycle - on_time) / self.time_scale)
                sd_notify("WATCHDOG=1")
        finally:
            self.hw.all_off()

    def tick(self, dt):
        """One control cycle of `dt` seconds. Returns heater duty 0..1."""
        self.hw.advance(dt, self.duty)
        self._read_sensor()
        self.duty = 0.0
        if self.state in ACTIVE:
            self._fire_tick(dt)
        else:
            self.setpoint = None
            self._idle_checks()
        self._publish()
        return self.duty

    def _read_sensor(self):
        try:
            self.temp = self.hw.read_temp(self.cfg["tc_offset"])
            self.sensor_error = ""
            self.bad_reads = 0
        except (SensorError, OSError) as exc:
            self.bad_reads += 1
            self.sensor_error = str(exc)

    def _fire_tick(self, dt):
        cfg = self.cfg
        self.fire_time += dt
        if self.bad_reads >= cfg["sensor_fault_limit"]:
            return self._abort(f"Thermocouple failure: {self.sensor_error}")
        temp = self.temp

        sp = self.schedule.setpoint(self.sched_time)
        seg = self.schedule.segment_at(self.sched_time)
        heating = self.schedule.heating_at(self.sched_time)
        lag = (sp - temp) if heating else (temp - sp)
        self.catching_up = (cfg["catch_up"] or seg.wait) and lag > cfg["catch_up_delta"]
        if self.state == FIRING and not self.catching_up:
            self.sched_time += dt
        self.setpoint = sp
        self.duty = self.pid.update(sp, temp, dt)
        self.energy_j += self.duty * dt * cfg["element_watts"]
        self.history.append((self.fire_time, temp, self.duty))
        window = max(cfg["stall_minutes"], cfg["runaway_minutes"]) * 60
        while self.history and self.history[0][0] < self.fire_time - window:
            self.history.popleft()

        # --- safety ---------------------------------------------------
        if temp > cfg["max_temp"]:
            return self._abort(f"Over max temperature ({temp:.0f} C)")
        if heating and temp > sp + cfg["overshoot_abort"]:
            return self._abort(f"Overshoot: {temp:.0f} C vs setpoint {sp:.0f} C")
        if self.fire_time > cfg["max_firing_hours"] * 3600:
            return self._abort("Maximum firing time exceeded")
        stalled = self._window(cfg["stall_minutes"], lambda d: d >= 0.95)
        if stalled and temp - stalled < cfg["stall_min_rise"]:
            return self._abort("Kiln not heating at full power - check elements, "
                               "relays and thermocouple placement")
        if self._runaway(temp):
            return self._abort("Temperature rising with heater off - possible stuck SSR")

        # --- bookkeeping ---------------------------------------------
        if self.fire_time >= self._next_log:
            self._next_log = self.fire_time + LOG_INTERVAL
            self._log_point(temp, sp, seg.step)
        if self.fire_time >= self._next_save:
            self._next_save = self.fire_time + 60
            self._save_state()
        if self.camera and cfg["timelapse_minutes"] and self.fire_time >= self._next_snapshot:
            self._next_snapshot = self.fire_time + cfg["timelapse_minutes"] * 60
            self._snapshot()
        if self.sched_time >= self.schedule.duration and not self.catching_up:
            self._finish(COMPLETE, f"{self.profile['name']} complete")

    def _window(self, minutes, pred):
        """If every sample in the last `minutes` matches pred, return the
        temperature at the start of that window, else None."""
        span = minutes * 60
        if not self.history or self.fire_time - self.history[0][0] < span:
            return None
        start = None
        for t, temp, duty in reversed(self.history):
            if not pred(duty):
                return None
            start = temp
            if t <= self.fire_time - span:
                return start
        return None

    def _runaway(self, temp):
        start = self._window(self.cfg["runaway_minutes"], lambda d: d == 0)
        return start is not None and temp - start >= self.cfg["runaway_rise"]

    def _idle_checks(self):
        if self.temp is None:
            return
        if self.temp > self.cfg["max_temp"] and self.state != ERROR:
            self.emergency_stop(f"Over max temperature while idle ({self.temp:.0f} C)")
        if not self.safe_open_notified and self.temp < self.cfg["safe_open_temp"]:
            self.safe_open_notified = True
            self._notify("Kiln cool", f"Kiln is at {self.temp:.0f} C - safe to open")

    def _abort(self, reason):
        log.error("ABORT: %s", reason)
        self.hw.all_off()
        self.duty = 0.0
        self.hw.buzzer.on()
        self._finish(ERROR, reason)

    def _finish(self, state, message):
        self.hw.all_off()
        self.duty = 0.0
        self.state = state
        self.message = message
        self.catching_up = False
        if self.temp is not None:
            self._log_point(self.temp, self.setpoint or self.temp, -1)
        self._write_meta(state)
        if self._csv:
            self._csv[0].close()
            self._csv = None
        try:
            os.remove(self.state_path)
        except FileNotFoundError:
            pass
        title = {COMPLETE: "Firing complete", STOPPED: "Firing stopped"}.get(state, "KILN ALARM")
        self._notify(title, message)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self):
        firing = self.state in ACTIVE
        step = seg_kind = None
        if self.schedule and firing:
            seg = self.schedule.segment_at(self.sched_time)
            step, seg_kind = seg.step + 1, seg.kind
        kwh = self.energy_j / 3.6e6
        return {
            "state": self.state,
            "message": self.message,
            "temp": None if self.temp is None else round(self.temp, 1),
            "sensor_error": self.sensor_error,
            "setpoint": None if self.setpoint is None else round(self.setpoint, 1),
            "duty": round(self.duty, 3),
            "heater_on": self.hw.heater.is_on,
            "contactor_on": self.hw.contactor.is_on,
            "catching_up": self.catching_up,
            "run_id": self.run_id,
            "profile": self.profile["name"] if self.profile else None,
            "step": step,
            "steps": len(self.profile["steps"]) if self.profile else None,
            "segment": seg_kind,
            "fire_time": round(self.fire_time),
            "sched_time": round(self.sched_time),
            "remaining": round(self.schedule.duration - self.sched_time) if firing else None,
            "kwh": round(kwh, 2),
            "cost": round(kwh * self.cfg["price_per_kwh"], 2),
            "simulated": self.hw.simulated,
            "camera": bool(self.camera and self.camera.available),
            "time": time.time(),
        }

    def run_detail(self):
        return {
            "run_id": self.run_id,
            "profile": self.profile,
            "plan": self.schedule.points() if self.schedule else [],
            "points": self.points,
        }

    def _publish(self):
        status = self.status()
        for fn in list(self.listeners):
            try:
                fn(status)
            except Exception:
                log.exception("status listener failed")

    def _notify(self, title, message):
        if self.notifier:
            self.notifier.send(title, message)

    # ------------------------------------------------------------------
    # Persistence: run logs and power-loss recovery
    # ------------------------------------------------------------------

    def _run_dir(self):
        path = os.path.join(self.log_dir, self.run_id)
        os.makedirs(path, exist_ok=True)
        return path

    def _open_run_log(self, append=False):
        path = os.path.join(self._run_dir(), "log.csv")
        f = open(path, "a" if append else "w", newline="")
        writer = csv.writer(f)
        if not append:
            writer.writerow(["time_s", "temp_c", "setpoint_c", "duty", "step"])
        self._csv = (f, writer)
        self._write_meta("running")

    def _log_point(self, temp, sp, step):
        self.points.append([round(self.fire_time), round(temp, 1), round(sp, 1)])
        if self._csv:
            self._csv[1].writerow([round(self.fire_time), round(temp, 2), round(sp, 2),
                                   round(self.duty, 3), step + 1])
            self._csv[0].flush()

    def _write_meta(self, outcome):
        if not self.run_id:
            return
        kwh = self.energy_j / 3.6e6
        meta = {
            "run_id": self.run_id,
            "profile": self.profile,
            "started": self.run_id,
            "outcome": outcome,
            "message": self.message,
            "duration_s": round(self.fire_time),
            "peak_c": max((p[1] for p in self.points), default=None),
            "kwh": round(kwh, 2),
            "cost": round(kwh * self.cfg["price_per_kwh"], 2),
            "start_temp": self.schedule.segments[0].t0 if self.schedule else None,
        }
        with open(os.path.join(self._run_dir(), "meta.json"), "w") as f:
            json.dump(meta, f, indent=2)

    def _snapshot(self):
        path = os.path.join(self._run_dir(), "snapshots")
        os.makedirs(path, exist_ok=True)
        self.camera.save_snapshot(os.path.join(path, f"{round(self.fire_time):07d}.jpg"))

    def _save_state(self):
        state = {
            "wall_time": time.time(),
            "profile": self.profile,
            "start_temp": self.schedule.segments[0].t0,
            "sched_time": self.sched_time,
            "fire_time": self.fire_time,
            "energy_j": self.energy_j,
            "run_id": self.run_id,
            "points": self.points[-2000:],
        }
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f)
        os.replace(tmp, self.state_path)
        self._write_meta("running")

    def _try_resume(self):
        """After a power cut or reboot, continue the firing if the outage
        was short. Otherwise record it as interrupted."""
        try:
            with open(self.state_path) as f:
                saved = json.load(f)
        except (OSError, ValueError):
            return
        os.remove(self.state_path)
        outage = time.time() - saved["wall_time"]
        limit = self.cfg["auto_resume_minutes"] * 60
        self.profile = saved["profile"]
        self.run_id = saved["run_id"]
        self.schedule = Schedule(self.profile, saved["start_temp"])
        self.sched_time = saved["sched_time"]
        self.fire_time = saved["fire_time"] + outage
        self.energy_j = saved["energy_j"]
        self.points = saved["points"]
        if outage > limit or self.temp is None or self.sensor_error:
            self.message = f"Firing interrupted by power loss ({outage / 60:.0f} min) - not resumed"
            self.state = ERROR
            self._write_meta(ERROR)
            self._notify("KILN ALARM", self.message)
            return
        # If the kiln cooled during the outage, rewind to where the schedule
        # last matched the actual temperature instead of chasing a jump.
        t = self.sched_time
        while t > 0 and self.schedule.heating_at(t) and self.schedule.setpoint(t) > self.temp + 5:
            t -= 30
        self.sched_time = max(0.0, t)
        self._open_run_log(append=True)
        self.pid.reset()
        self.hw.contactor.on()
        self.state = FIRING
        self.message = f"Resumed after {outage / 60:.1f} min power loss"
        self._notify("Firing resumed", self.message)
