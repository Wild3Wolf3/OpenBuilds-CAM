import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

from kilnctl import web as webmod
from kilnctl.config import Config
from kilnctl.controller import Controller
from kilnctl.hardware import Hardware
from kilnctl.profiles import ProfileStore

PROFILE = {"profile": {"name": "t", "steps": [{"target": 300, "minutes": 60, "hold": 0}]}}


def run(tmp_path, scenario, remote=None):
    """Run `scenario(client, ctl, cfg)` against the real app (no control loop)."""
    async def main():
        cfg = Config(str(tmp_path))
        cfg.update({"simulate": True})
        ctl = Controller(cfg, Hardware(cfg))
        ctl.tick(2.0)
        app = webmod.build_app(cfg, ctl, ProfileStore(str(tmp_path)), None)
        if remote:  # pretend every request comes from this address
            @webmod.web.middleware
            async def fake_remote(request, handler):
                return await handler(request.clone(remote=remote))
            app.middlewares.insert(0, fake_remote)
        async with TestClient(TestServer(app)) as client:
            await scenario(client, ctl, cfg)
    asyncio.run(main())


@pytest.fixture(autouse=True)
def fast_pin_delay(monkeypatch):
    real = asyncio.sleep
    monkeypatch.setattr(webmod.asyncio, "sleep", lambda s: real(0))


def test_firing_lock_pin(tmp_path):
    async def scenario(client, ctl, cfg):
        cfg.set_control_pin("4321")
        # Not firing yet: nothing is locked.
        assert (await client.post("/api/firing/start", json=PROFILE)).status == 200
        assert (await client.get("/api/status")).status == 200
        assert ctl.status()["control_locked"] is True

        r = await client.post("/api/firing/stop")
        assert r.status == 403
        assert (await r.json())["pin_required"] is True
        assert (await client.post("/api/firing/hold", json={"pin": "0000"})).status == 403
        assert (await client.put("/api/settings", json={"pid_kp": 1.0})).status == 403
        assert cfg["pid_kp"] != 1.0
        assert ctl.state == "firing"

        assert (await client.post("/api/firing/hold", json={"pin": "4321"})).status == 200
        assert ctl.state == "holding"
        r = await client.post("/api/firing/resume", headers={"X-Kiln-Pin": "4321"})
        assert r.status == 200 and ctl.state == "firing"

        # Emergency stop never needs the PIN.
        assert (await client.post("/api/firing/estop")).status == 200
        assert ctl.state == "error" and not ctl.hw.contactor.is_on
        # Once nothing is running, settings are unlocked again.
        assert (await client.put("/api/settings", json={"pid_kp": 0.05})).status == 200
    run(tmp_path, scenario)


def test_pin_lockout(tmp_path):
    async def scenario(client, ctl, cfg):
        cfg.set_control_pin("4321")
        await client.post("/api/firing/start", json=PROFILE)
        for _ in range(webmod.PIN_MAX_TRIES):
            assert (await client.post("/api/firing/stop", json={"pin": "1111"})).status == 403
        # Locked out - even the right PIN is refused for a while.
        assert (await client.post("/api/firing/stop", json={"pin": "4321"})).status == 429
        assert ctl.state == "firing"
    run(tmp_path, scenario)


def test_interface_passcode(tmp_path):
    async def scenario(client, ctl, cfg):
        r = await client.put("/api/settings", json={"new_password": "2468"})
        assert r.status == 200
        client.session.cookie_jar.clear()
        assert (await client.get("/api/status")).status == 401
        auth = await (await client.get("/api/auth")).json()
        assert auth == {"required": True, "numeric": True, "authed": False}
        assert (await client.post("/api/login", json={"password": "1357"})).status == 403
        assert (await client.post("/api/login", json={"password": "2468"})).status == 200
        assert (await client.get("/api/status")).status == 200
    run(tmp_path, scenario)


def test_locked_screen_estop_only_from_touchscreen(tmp_path):
    async def remote(client, ctl, cfg):
        cfg.set_password("2468")
        assert (await client.post("/api/firing/estop")).status == 401
    run(tmp_path, remote, remote="192.168.1.50")

    async def local(client, ctl, cfg):
        cfg.set_password("2468")
        assert (await client.post("/api/firing/estop")).status == 200
        assert (await client.post("/api/firing/stop")).status == 401
    run(tmp_path, local, remote="127.0.0.1")


def test_bad_codes_rejected_without_partial_save(tmp_path):
    async def scenario(client, ctl, cfg):
        r = await client.put("/api/settings", json={"new_control_pin": "12ab", "kiln_name": "X"})
        assert r.status == 400
        assert cfg["kiln_name"] != "X" and not cfg["control_pin_hash"]
        assert (await client.put("/api/settings", json={"new_password": "12"})).status == 400
    run(tmp_path, scenario)
