import argparse
import asyncio
import logging
import os

from aiohttp import web

from .camera import Camera
from .config import DATA_DIR, Config
from .controller import Controller
from .hardware import Hardware
from .notify import Notifier
from .profiles import ProfileStore
from .web import build_app


def main():
    parser = argparse.ArgumentParser(prog="kilnctl", description="Kiln controller")
    parser.add_argument("--data-dir", default=DATA_DIR)
    parser.add_argument("--simulate", action="store_true", help="run without hardware")
    parser.add_argument("--port", type=int, help="override http_port")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.simulate:
        os.environ["KILN_SIMULATE"] = "1"
    cfg = Config(args.data_dir)
    hw = Hardware(cfg)

    async def on_startup(app):
        camera = None
        if cfg["camera_enabled"] and not hw.simulated:
            camera = Camera(cfg, asyncio.get_running_loop())
        app["camera"] = camera
        app["ctl"].camera = camera
        app["control_task"] = asyncio.get_running_loop().create_task(app["ctl"].run())

    async def on_cleanup(app):
        hw.all_off()
        app["control_task"].cancel()

    ctl = Controller(cfg, hw, notifier=Notifier(cfg))
    app = build_app(cfg, ctl, ProfileStore(cfg.data_dir), None)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    try:
        web.run_app(app, port=args.port or cfg["http_port"], print=None)
    finally:
        hw.all_off()


if __name__ == "__main__":
    main()
