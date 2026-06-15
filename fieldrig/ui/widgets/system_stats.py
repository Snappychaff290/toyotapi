"""Live system stats: CPU load, memory, CPU temperature.

Read straight from /proc and /sys -- no dependencies, works on the Pi
and any Linux dev box. Temperature is the Pi's thermal zone when
present, "--" otherwise.
"""

import os
from pathlib import Path

from textual.widgets import Static

METER_SEGMENTS = 10
THERMAL = Path("/sys/class/thermal/thermal_zone0/temp")


def _meter(fraction: float) -> str:
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * METER_SEGMENTS)
    return "█" * filled + "░" * (METER_SEGMENTS - filled)


def _meminfo() -> tuple[float, float]:
    """Returns (used_gb, total_gb)."""
    fields = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, _, rest = line.partition(":")
            fields[key] = int(rest.split()[0])  # kB
    total = fields.get("MemTotal", 0)
    available = fields.get("MemAvailable", 0)
    return (total - available) / 1024 / 1024, total / 1024 / 1024


class SystemStats(Static):
    def on_mount(self) -> None:
        self.set_interval(2.0, self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        cpus = os.cpu_count() or 1
        load = os.getloadavg()[0] / cpus
        cpu_line = f"CPU  {_meter(load)}  {round(load * 100):>3}%"

        try:
            used, total = _meminfo()
            ram_line = (f"RAM  {_meter(used / total if total else 0)}  "
                        f"{used:.1f} / {total:.1f}G")
        except OSError:
            ram_line = "RAM  [#006618]unavailable[/]"

        try:
            celsius = int(THERMAL.read_text().strip()) / 1000
            tmp_line = f"TMP  {_meter(celsius / 85)}  {celsius:.0f}°C"
        except (OSError, ValueError):
            tmp_line = "TMP  [#006618]no sensor[/]"

        self.update(f"{cpu_line}\n{ram_line}\n{tmp_line}")
