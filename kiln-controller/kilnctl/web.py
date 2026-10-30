"""HTTP API, websocket status feed, camera stream and static web UI."""
import asyncio
import csv
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import signal
import time

from aiohttp import web

from . import wifi
from .controller import ACTIVE

log = logging.getLogger(__name__)
STATIC = os.path.join(os.path.dirname(__file__), "static")
COOKIE = "kiln_auth"
RUN_ID = re.compile(r"^[0-9]{8}-[0-9]{6}$")
PUBLIC_PATHS = ("/api/login", "/api/auth")


def _token(cfg):
    return hmac.new(cfg["secret"].encode(), cfg["password_hash"].encode(), hashlib.sha256).hexdigest()


def _authed(request):
    cfg = request.app["cfg"]
    if not cfg["password_hash"]:
        return True
    return hmac.compare_digest(request.cookies.get(COOKIE, ""), _token(cfg))


@web.middleware
async def auth_middleware(request, handler):
    path = request.path
    protected = path.startswith(("/api/", "/ws", "/camera/")) and path not in PUBLIC_PATHS
    if protected and not _authed(request):
        raise web.HTTPUnauthorized(text="login required")
    return await handler(request)


@web.middleware
async def error_middleware(request, handler):
    try:
        return await handler(request)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except RuntimeError as exc:
        return web.json_response({"error": str(exc)}, status=503)


async def _json(request):
    try:
        return await request.json()
    except json.JSONDecodeError:
        raise ValueError("invalid JSON body")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

async def auth_status(request):
    return web.json_response({"required": bool(request.app["cfg"]["password_hash"]),
                              "authed": _authed(request)})


async def login(request):
    cfg = request.app["cfg"]
    body = await _json(request)
    await asyncio.sleep(0.5)  # slow down guessing
    if not cfg.check_password(str(body.get("password", ""))):
        raise web.HTTPForbidden(text="wrong password")
    resp = web.json_response({"ok": True})
    resp.set_cookie(COOKIE, _token(cfg), max_age=90 * 86400, httponly=True, samesite="Strict")
    return resp


async def logout(request):
    resp = web.json_response({"ok": True})
    resp.del_cookie(COOKIE)
    return resp


# ---------------------------------------------------------------------------
# Status / firing control
# ---------------------------------------------------------------------------

async def get_status(request):
    return web.json_response(request.app["ctl"].status())


async def get_run(request):
    return web.json_response(request.app["ctl"].run_detail())


async def firing_action(request):
    ctl = request.app["ctl"]
    action = request.match_info["action"]
    if action == "start":
        body = await _json(request)
        if body.get("profile_id"):
            profile = request.app["store"].get(body["profile_id"])
            if not profile:
                raise ValueError("no such profile")
        else:
            profile = body.get("profile")
        ctl.start(profile)
    elif action == "stop":
        ctl.stop()
    elif action == "estop":
        ctl.emergency_stop()
    elif action == "hold":
        ctl.hold()
    elif action == "resume":
        ctl.resume()
    elif action == "skip":
        ctl.skip_step()
    elif action == "ack":
        ctl.acknowledge()
    else:
        raise web.HTTPNotFound()
    return web.json_response(ctl.status())


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

async def list_profiles(request):
    return web.json_response(request.app["store"].all())


async def create_profile(request):
    return web.json_response(request.app["store"].save(await _json(request)))


async def update_profile(request):
    pid = request.match_info["pid"]
    return web.json_response(request.app["store"].save(await _json(request), pid))


async def delete_profile(request):
    request.app["store"].delete(request.match_info["pid"])
    return web.json_response({"ok": True})


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def _run_dir(request):
    run_id = request.match_info["run_id"]
    if not RUN_ID.match(run_id):
        raise web.HTTPNotFound()
    path = os.path.join(request.app["ctl"].log_dir, run_id)
    if not os.path.isdir(path):
        raise web.HTTPNotFound()
    return path


async def list_history(request):
    log_dir = request.app["ctl"].log_dir
    runs = []
    for run_id in sorted(os.listdir(log_dir), reverse=True):
        try:
            with open(os.path.join(log_dir, run_id, "meta.json")) as f:
                meta = json.load(f)
        except (OSError, ValueError):
            continue
        meta["profile_name"] = (meta.pop("profile") or {}).get("name")
        runs.append(meta)
    return web.json_response(runs)


async def get_history(request):
    path = _run_dir(request)
    with open(os.path.join(path, "meta.json")) as f:
        meta = json.load(f)
    points = []
    try:
        with open(os.path.join(path, "log.csv")) as f:
            for row in csv.DictReader(f):
                points.append([float(row["time_s"]), float(row["temp_c"]), float(row["setpoint_c"])])
    except OSError:
        pass
    snaps = os.path.join(path, "snapshots")
    meta["points"] = points
    meta["snapshots"] = sorted(os.listdir(snaps)) if os.path.isdir(snaps) else []
    return web.json_response(meta)


async def history_csv(request):
    path = os.path.join(_run_dir(request), "log.csv")
    return web.FileResponse(path, headers={
        "Content-Disposition": f'attachment; filename="firing-{request.match_info["run_id"]}.csv"'})


async def history_snapshot(request):
    name = request.match_info["name"]
    if not re.fullmatch(r"[0-9]{7}\.jpg", name):
        raise web.HTTPNotFound()
    return web.FileResponse(os.path.join(_run_dir(request), "snapshots", name))


async def delete_history(request):
    if request.match_info["run_id"] == request.app["ctl"].run_id and request.app["ctl"].state in ACTIVE:
        raise ValueError("cannot delete the running firing")
    shutil.rmtree(_run_dir(request))
    return web.json_response({"ok": True})


# ---------------------------------------------------------------------------
# Settings / system
# ---------------------------------------------------------------------------

async def get_settings(request):
    return web.json_response(request.app["cfg"].public())


async def put_settings(request):
    cfg, ctl = request.app["cfg"], request.app["ctl"]
    body = await _json(request)
    new_password = body.pop("new_password", None)
    body.pop("password_set", None)
    cfg.update(body)
    if new_password is not None:
        cfg.set_password(new_password)
    ctl.pid.kp, ctl.pid.ki, ctl.pid.kd = cfg["pid_kp"], cfg["pid_ki"], cfg["pid_kd"]
    resp = web.json_response(cfg.public())
    if new_password is not None:
        resp.set_cookie(COOKIE, _token(cfg), max_age=90 * 86400, httponly=True, samesite="Strict")
    return resp


async def restart(request):
    if request.app["ctl"].state in ACTIVE:
        raise ValueError("stop the firing before restarting")
    asyncio.get_running_loop().call_later(1, os.kill, os.getpid(), signal.SIGTERM)
    return web.json_response({"ok": True})


async def wifi_status(request):
    return web.json_response(await wifi.status())


async def wifi_scan(request):
    return web.json_response(await wifi.scan())


async def wifi_connect(request):
    body = await _json(request)
    ssid = str(body.get("ssid", "")).strip()
    if not ssid:
        raise ValueError("SSID required")

    async def later():
        # Respond first: switching networks drops this very connection
        # when we're being reached through the setup hotspot.
        await asyncio.sleep(2)
        try:
            await wifi.connect(ssid, str(body.get("password", "")))
        except Exception as exc:
            log.error("wifi connect failed: %s", exc)

    asyncio.get_running_loop().create_task(later())
    return web.json_response({"ok": True, "message": f"Connecting to {ssid}. "
                              f"Reconnect your device to that network and browse to http://kiln.local"})


# ---------------------------------------------------------------------------
# Live data: websocket and camera
# ---------------------------------------------------------------------------

async def websocket(request):
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    request.app["sockets"].add(ws)
    try:
        await ws.send_json(request.app["ctl"].status())
        async for _ in ws:
            pass
    finally:
        request.app["sockets"].discard(ws)
    return ws


def make_broadcaster(app):
    state = {"last": 0.0, "last_state": None}

    def broadcast(status):
        now = time.monotonic()
        changed = status["state"] != state["last_state"]
        if not changed and now - state["last"] < 0.5:
            return
        state["last"], state["last_state"] = now, status["state"]
        for ws in list(app["sockets"]):
            if not ws.closed:
                asyncio.ensure_future(ws.send_json(status))
    return broadcast


async def camera_stream(request):
    cam = request.app["camera"]
    if not cam or not cam.available:
        raise web.HTTPNotFound(text="no camera")
    resp = web.StreamResponse(headers={
        "Content-Type": "multipart/x-mixed-replace; boundary=frame",
        "Cache-Control": "no-cache"})
    await resp.prepare(request)
    try:
        while True:
            frame = await cam.next_frame()
            await resp.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                             + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    return resp


async def camera_snapshot(request):
    cam = request.app["camera"]
    if not cam or not cam.frame:
        raise web.HTTPNotFound(text="no camera")
    return web.Response(body=cam.frame, content_type="image/jpeg",
                        headers={"Cache-Control": "no-cache"})


async def index(request):
    return web.FileResponse(os.path.join(STATIC, "index.html"))


def build_app(cfg, ctl, store, camera):
    app = web.Application(middlewares=[error_middleware, auth_middleware])
    app["cfg"], app["ctl"], app["store"], app["camera"] = cfg, ctl, store, camera
    app["sockets"] = set()
    ctl.listeners.append(make_broadcaster(app))
    r = app.router
    r.add_get("/", index)
    r.add_get("/api/auth", auth_status)
    r.add_post("/api/login", login)
    r.add_post("/api/logout", logout)
    r.add_get("/api/status", get_status)
    r.add_get("/api/run", get_run)
    r.add_post("/api/firing/{action}", firing_action)
    r.add_get("/api/profiles", list_profiles)
    r.add_post("/api/profiles", create_profile)
    r.add_put("/api/profiles/{pid}", update_profile)
    r.add_delete("/api/profiles/{pid}", delete_profile)
    r.add_get("/api/history", list_history)
    r.add_get("/api/history/{run_id}", get_history)
    r.add_get("/api/history/{run_id}/log.csv", history_csv)
    r.add_get("/api/history/{run_id}/snapshots/{name}", history_snapshot)
    r.add_delete("/api/history/{run_id}", delete_history)
    r.add_get("/api/settings", get_settings)
    r.add_put("/api/settings", put_settings)
    r.add_post("/api/system/restart", restart)
    r.add_get("/api/wifi", wifi_status)
    r.add_get("/api/wifi/scan", wifi_scan)
    r.add_post("/api/wifi/connect", wifi_connect)
    r.add_get("/ws", websocket)
    r.add_get("/camera/stream.mjpg", camera_stream)
    r.add_get("/camera/snapshot.jpg", camera_snapshot)
    r.add_static("/static/", STATIC)
    return app
