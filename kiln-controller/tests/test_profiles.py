import pytest

from kilnctl.profiles import MAX_STEPS, ProfileStore, Schedule, validate


def test_schedule_interpolates_from_start_temp():
    s = Schedule(validate({"name": "x", "steps": [
        {"target": 100, "minutes": 60, "hold": 30},
        {"target": 500, "minutes": 120, "hold": 0}]}), 20)
    assert s.setpoint(0) == 20
    assert s.setpoint(1800) == pytest.approx(60)
    assert s.setpoint(3600 + 900) == 100
    assert s.setpoint(5400 + 3600) == pytest.approx(300)
    assert s.duration == 5400 + 7200
    assert s.points()[0] == (0.0, 20)


def test_cooling_step_is_not_heating():
    s = Schedule(validate({"name": "x", "steps": [
        {"target": 800, "minutes": 60, "hold": 0},
        {"target": 500, "minutes": 60, "hold": 10}]}), 20)
    assert s.heating_at(100)
    assert not s.heating_at(3700)
    assert not s.heating_at(7300)


def test_step_limit():
    steps = [{"target": 100, "minutes": 1, "hold": 0}] * (MAX_STEPS + 1)
    with pytest.raises(ValueError):
        validate({"name": "x", "steps": steps})
    validate({"name": "x", "steps": steps[:MAX_STEPS]})


@pytest.mark.parametrize("bad", [
    {"name": "", "steps": [{"target": 1, "minutes": 1}]},
    {"name": "x", "steps": []},
    {"name": "x", "steps": [{"target": 5000, "minutes": 1}]},
    {"name": "x", "steps": [{"target": 100, "minutes": -1}]},
    {"name": "x", "steps": [{"target": "hot"}]},
])
def test_validation_rejects(bad):
    with pytest.raises(ValueError):
        validate(bad)


def test_store_roundtrip(tmp_path):
    store = ProfileStore(str(tmp_path))
    presets = store.all()
    assert any(p["builtin"] for p in presets)
    saved = store.save({"name": "My Bisque", "steps": [{"target": 999, "minutes": 300, "hold": 10}]})
    assert saved["id"] == "my-bisque"
    again = store.save({"name": "My Bisque", "steps": [{"target": 999, "minutes": 300, "hold": 10}]})
    assert again["id"] == "my-bisque-2"
    store.save({"name": "Renamed", "steps": [{"target": 990, "minutes": 300, "hold": 0}]}, "my-bisque")
    assert store.get("my-bisque")["name"] == "Renamed"
    with pytest.raises(ValueError):
        store.save({"name": "x", "steps": [{"target": 1, "minutes": 1}]}, "glaze-cone-6")
    store.delete("my-bisque")
    assert store.get("my-bisque") is None
    with pytest.raises(ValueError):
        store.delete("glaze-cone-6")
