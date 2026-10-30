"""Push notifications to an ntfy.sh topic (or any URL accepting a text POST)."""
import asyncio
import logging

import aiohttp

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, cfg):
        self.cfg = cfg

    def send(self, title, message):
        url = self.cfg["notify_url"]
        if not url:
            return
        try:
            asyncio.get_running_loop().create_task(self._post(url, title, message))
        except RuntimeError:
            pass  # no event loop (tests)

    async def _post(self, url, title, message):
        name = self.cfg["kiln_name"]
        headers = {"Title": f"{name}: {title}"}
        if "ALARM" in title:
            headers["Priority"] = "urgent"
            headers["Tags"] = "rotating_light"
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
                await s.post(url, data=message.encode(), headers=headers)
        except Exception as exc:
            log.warning("notification failed: %s", exc)
