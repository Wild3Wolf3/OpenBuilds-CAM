"""Wi-Fi management through NetworkManager's nmcli."""
import asyncio
import shutil


async def _nmcli(*args, timeout=40):
    if not shutil.which("nmcli"):
        raise RuntimeError("NetworkManager (nmcli) is not available on this system")
    proc = await asyncio.create_subprocess_exec(
        "nmcli", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await asyncio.wait_for(proc.communicate(), timeout)
    if proc.returncode != 0:
        raise RuntimeError(err.decode().strip() or "nmcli failed")
    return out.decode()


def _split(line):
    """Split nmcli terse output, honouring backslash-escaped colons."""
    fields, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur, esc = cur + ch, False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            fields.append(cur)
            cur = ""
        else:
            cur += ch
    fields.append(cur)
    return fields


async def status():
    out = await _nmcli("-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi")
    for line in out.splitlines():
        active, ssid, signal = (_split(line) + ["", "", ""])[:3]
        if active == "yes":
            return {"connected": True, "ssid": ssid, "signal": int(signal or 0)}
    return {"connected": False, "ssid": None, "signal": None}


async def scan():
    out = await _nmcli("-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "yes")
    seen = {}
    for line in out.splitlines():
        ssid, signal, security = (_split(line) + ["", "", ""])[:3]
        if ssid and (ssid not in seen or int(signal or 0) > seen[ssid]["signal"]):
            seen[ssid] = {"ssid": ssid, "signal": int(signal or 0), "secure": bool(security)}
    return sorted(seen.values(), key=lambda n: -n["signal"])


async def connect(ssid, password):
    args = ["dev", "wifi", "connect", ssid]
    if password:
        args += ["password", password]
    await _nmcli(*args, timeout=60)
    # Leave setup hotspot mode once we're on a real network.
    try:
        await _nmcli("connection", "down", "Kiln-Setup")
    except RuntimeError:
        pass
