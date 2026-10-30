"""Firing profiles (time/temperature step programs) and their storage.

A profile is a list of up to MAX_STEPS steps. Each step says: go from
wherever the kiln is now to `target` deg C in `minutes`, then hold there
for `hold` minutes. `minutes == 0` means "as fast as possible": the
heater runs flat out and the schedule waits until the target is reached.
A target lower than the previous one is a controlled cool-down.
"""
import json
import os
import re
import time

MAX_STEPS = 35
MAX_TARGET = 1400.0
PRESET_DIR = os.path.join(os.path.dirname(__file__), "presets")


def validate(data):
    if not isinstance(data, dict):
        raise ValueError("profile must be an object")
    name = str(data.get("name", "")).strip()
    if not 1 <= len(name) <= 60:
        raise ValueError("name must be 1-60 characters")
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("profile needs at least one step")
    if len(steps) > MAX_STEPS:
        raise ValueError(f"a profile may have at most {MAX_STEPS} steps")
    clean = []
    for i, step in enumerate(steps, 1):
        try:
            target = float(step["target"])
            minutes = float(step.get("minutes", 0))
            hold = float(step.get("hold", 0))
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"step {i}: target, minutes and hold must be numbers")
        if not 0 <= target <= MAX_TARGET:
            raise ValueError(f"step {i}: target must be 0-{MAX_TARGET:.0f} C")
        if minutes < 0 or hold < 0 or minutes > 6000 or hold > 6000:
            raise ValueError(f"step {i}: times must be 0-6000 minutes")
        clean.append({"target": round(target, 2), "minutes": round(minutes, 2), "hold": round(hold, 2)})
    return {
        "name": name,
        "description": str(data.get("description", ""))[:500],
        "steps": clean,
    }


def slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:60] or "profile"


class Segment:
    __slots__ = ("start", "end", "t0", "t1", "step", "kind", "wait")

    def __init__(self, start, end, t0, t1, step, kind, wait=False):
        self.start, self.end, self.t0, self.t1 = start, end, t0, t1
        self.step, self.kind, self.wait = step, kind, wait

    def setpoint(self, t):
        if self.end <= self.start:
            return self.t1
        frac = (t - self.start) / (self.end - self.start)
        return self.t0 + (self.t1 - self.t0) * min(1.0, max(0.0, frac))


class Schedule:
    """Piecewise-linear setpoint curve built from a profile and start temp.

    Times are seconds of *schedule* time; the controller may pause the
    schedule clock while the kiln catches up.
    """

    def __init__(self, profile, start_temp):
        self.profile = profile
        self.segments = []
        t, temp = 0.0, float(start_temp)
        for i, step in enumerate(profile["steps"]):
            ramp = step["minutes"] * 60.0
            asap = ramp == 0
            self.segments.append(Segment(t, t + ramp, temp, step["target"], i, "ramp", wait=asap))
            t += ramp
            temp = step["target"]
            # A zero-length hold still exists so "as fast as possible" ramps
            # have somewhere to wait for the kiln to arrive.
            hold = step["hold"] * 60.0
            self.segments.append(Segment(t, t + hold, temp, temp, i, "hold", wait=asap))
            t += hold
        self.duration = t

    def segment_at(self, t):
        for seg in self.segments:
            if t < seg.end:
                return seg
        return self.segments[-1]

    def setpoint(self, t):
        return self.segment_at(min(t, self.duration)).setpoint(t)

    def heating_at(self, t):
        seg = self.segment_at(t)
        if seg.kind == "ramp":
            return seg.t1 >= seg.t0
        prev = [s for s in self.segments if s.step == seg.step and s.kind == "ramp"][0]
        return prev.t1 >= prev.t0

    def step_end(self, step):
        return max(s.end for s in self.segments if s.step == step)

    def points(self):
        pts = [(0.0, self.segments[0].t0)]
        for seg in self.segments:
            if seg.end > pts[-1][0] or seg.t1 != pts[-1][1]:
                pts.append((seg.end, seg.t1))
        return pts


class ProfileStore:
    def __init__(self, data_dir):
        self.dir = os.path.join(data_dir, "profiles")
        os.makedirs(self.dir, exist_ok=True)

    def _load_dir(self, path, builtin):
        out = {}
        if not os.path.isdir(path):
            return out
        for fn in sorted(os.listdir(path)):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(path, fn)) as f:
                    prof = validate(json.load(f))
            except (OSError, ValueError):
                continue
            prof["id"] = fn[:-5]
            prof["builtin"] = builtin
            out[prof["id"]] = prof
        return out

    def all(self):
        profiles = self._load_dir(PRESET_DIR, True)
        profiles.update(self._load_dir(self.dir, False))
        return sorted(profiles.values(), key=lambda p: (not p["builtin"], p["name"].lower()))

    def get(self, pid):
        for prof in self.all():
            if prof["id"] == pid:
                return prof
        return None

    def save(self, data, pid=None):
        prof = validate(data)
        if not pid:
            pid = base = slugify(prof["name"])
            n = 2
            while self.get(pid):
                pid = f"{base}-{n}"
                n += 1
        elif not re.fullmatch(r"[a-z0-9-]{1,64}", pid):
            raise ValueError("bad profile id")
        existing = self.get(pid)
        if existing and existing["builtin"] and not os.path.exists(self._path(pid)):
            raise ValueError("built-in presets are read-only; use Save As")
        prof["updated"] = int(time.time())
        tmp = self._path(pid) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(prof, f, indent=2)
        os.replace(tmp, self._path(pid))
        prof["id"] = pid
        prof["builtin"] = False
        return prof

    def delete(self, pid):
        if not re.fullmatch(r"[a-z0-9-]{1,64}", pid) or not os.path.exists(self._path(pid)):
            raise ValueError("no such custom profile")
        os.remove(self._path(pid))

    def _path(self, pid):
        return os.path.join(self.dir, pid + ".json")
