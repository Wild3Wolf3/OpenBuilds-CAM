import pytest

from kilnctl.config import Config
from kilnctl.controller import COMPLETE, ERROR, FIRING, Controller
from kilnctl.hardware import Hardware
from kilnctl.profiles import ProfileStore

CYCLE = 2.0


@pytest.fixture
def ctl(tmp_path):
    cfg = Config(str(tmp_path))
    cfg.update({"simulate": True})
    c = Controller(cfg, Hardware(cfg))
    c.tick(CYCLE)
    return c


def run(ctl, hours, until=None):
    for _ in range(int(hours * 3600 / CYCLE)):
        ctl.tick(CYCLE)
        if until and until(ctl):
            break


def test_cone6_glaze_tracks_schedule(ctl, tmp_path):
    profile = ProfileStore(str(tmp_path)).get("glaze-cone-6")
    ctl.start(profile)
    worst = 0.0
    while ctl.state == FIRING:
        ctl.tick(CYCLE)
        if ctl.sched_time > 600 and not ctl.catching_up:
            worst = max(worst, abs(ctl.temp - ctl.setpoint))
        assert ctl.fire_time < 14 * 3600
    assert ctl.state == COMPLETE, ctl.message
    assert worst < 10, worst
    assert max(p[1] for p in ctl.points) == pytest.approx(1222, abs=8)
    assert ctl.status()["kwh"] > 10


def test_asap_step_waits_for_kiln(ctl):
    ctl.start({"name": "fast", "steps": [{"target": 300, "minutes": 0, "hold": 10}]})
    run(ctl, 3, until=lambda c: c.state != FIRING)
    assert ctl.state == COMPLETE
    # schedule only counts the hold once the kiln got there
    assert ctl.fire_time > 600 + 300


def test_glass_cooling_steps(ctl, tmp_path):
    ctl.start(ProfileStore(str(tmp_path)).get("glass-full-fuse"))
    run(ctl, 20, until=lambda c: c.state != FIRING)
    assert ctl.state == COMPLETE, ctl.message


def test_open_thermocouple_aborts(ctl):
    ctl.start({"name": "t", "steps": [{"target": 500, "minutes": 120, "hold": 0}]})
    run(ctl, 0.1)

    def broken(offset=0.0):
        from kilnctl.hardware import SensorError
        raise SensorError("thermocouple open circuit")
    ctl.hw.read_temp = broken
    run(ctl, 0.1)
    assert ctl.state == ERROR
    assert "open circuit" in ctl.message
    assert not ctl.hw.heater.is_on and not ctl.hw.contactor.is_on


def test_dead_element_detected(ctl):
    ctl.start({"name": "t", "steps": [{"target": 1000, "minutes": 0, "hold": 0}]})
    ctl.hw.sim.watts = 0  # elements burnt out
    run(ctl, 1)
    assert ctl.state == ERROR
    assert "not heating" in ctl.message


def test_stuck_relay_detected(ctl):
    ctl.start({"name": "t", "steps": [{"target": 300, "minutes": 30, "hold": 600}]})
    run(ctl, 2)
    real = ctl.hw.advance
    ctl.hw.advance = lambda dt, duty: real(dt, 1.0)  # SSR welded on
    run(ctl, 1)
    assert ctl.state == ERROR


def test_stop_turns_everything_off(ctl):
    ctl.start({"name": "t", "steps": [{"target": 300, "minutes": 30, "hold": 0}]})
    run(ctl, 0.05)
    assert ctl.hw.contactor.is_on
    ctl.stop()
    assert ctl.state == "stopped"
    assert not ctl.hw.contactor.is_on and not ctl.hw.heater.is_on


def test_rejects_profile_over_max(ctl):
    ctl.cfg.update({"max_temp": 1000.0})
    with pytest.raises(ValueError):
        ctl.start({"name": "t", "steps": [{"target": 1200, "minutes": 30, "hold": 0}]})


def test_power_loss_resume(ctl, tmp_path):
    ctl.start({"name": "t", "steps": [{"target": 600, "minutes": 240, "hold": 0}]})
    run(ctl, 1)
    ctl._save_state()
    sched = ctl.sched_time
    again = Controller(ctl.cfg, ctl.hw)
    again._read_sensor()
    again._try_resume()
    assert again.state == FIRING
    assert again.sched_time == pytest.approx(sched, abs=60)


def test_hold_and_skip(ctl):
    ctl.start({"name": "t", "steps": [{"target": 200, "minutes": 60, "hold": 0},
                                      {"target": 400, "minutes": 60, "hold": 0}]})
    run(ctl, 0.25)
    ctl.hold()
    frozen = ctl.sched_time
    run(ctl, 0.25)
    assert ctl.sched_time == frozen and ctl.state == "holding"
    ctl.resume()
    ctl.skip_step()
    assert ctl.schedule.segment_at(ctl.sched_time).step == 1
