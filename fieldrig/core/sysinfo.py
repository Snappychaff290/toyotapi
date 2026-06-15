"""System stats from /proc and /sys -- no dependencies.

read_sysinfo() returns a snapshot; sysinfo_task() emits it on the bus
as system_update every couple of seconds for the dashboard.
"""

import asyncio
import os
from pathlib import Path
from typing import Any

from .events import EventBus

THERMAL = Path("/sys/class/thermal/thermal_zone0/temp")


def read_sysinfo() -> dict[str, Any]:
    cpus = os.cpu_count() or 1
    info: dict[str, Any] = {
        "cpu": min(1.0, os.getloadavg()[0] / cpus),
        "ram_used": None,
        "ram_total": None,
        "temp": None,
    }
    try:
        fields = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, _, rest = line.partition(":")
                fields[key] = int(rest.split()[0])  # kB
        total = fields.get("MemTotal", 0)
        available = fields.get("MemAvailable", 0)
        info["ram_used"] = round((total - available) / 1024 / 1024, 2)
        info["ram_total"] = round(total / 1024 / 1024, 2)
    except OSError:
        pass
    try:
        info["temp"] = round(int(THERMAL.read_text().strip()) / 1000, 1)
    except (OSError, ValueError):
        pass
    return info


async def sysinfo_task(bus: EventBus, interval: float = 2.0) -> None:
    while True:
        bus.emit("system_update", read_sysinfo())
        await asyncio.sleep(interval)
