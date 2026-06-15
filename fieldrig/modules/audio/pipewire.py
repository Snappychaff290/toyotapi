"""PipeWire control via wpctl (WirePlumber CLI).

Subprocess-based on purpose: zero pip dependencies, works on any
PipeWire system, and degrades to unavailable on dev boxes without it.
"""

import asyncio
import re
import shutil

from ...config import MAX_VOLUME
from ...logging_setup import get_module_logger

log = get_module_logger("audio")

SINK = "@DEFAULT_AUDIO_SINK@"


class PipeWire:
    def __init__(self) -> None:
        self.available = shutil.which("wpctl") is not None
        if not self.available:
            log.info("wpctl not found; PipeWire control disabled")

    async def _wpctl(self, *args: str, timeout: float = 5.0) -> str | None:
        if not self.available:
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
                "wpctl", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout)
            if proc.returncode != 0:
                return None
            return stdout.decode(errors="replace")
        except (asyncio.TimeoutError, OSError):
            log.exception("wpctl %s failed", " ".join(args))
            return None

    async def get_volume(self) -> tuple[float, bool] | None:
        """Returns (volume 0..1+, muted) for the default sink."""
        out = await self._wpctl("get-volume", SINK)
        if not out:
            return None
        match = re.search(r"Volume:\s*([\d.]+)", out)
        if not match:
            return None
        return float(match.group(1)), "[MUTED]" in out

    async def set_volume(self, volume: float) -> None:
        volume = max(0.0, min(MAX_VOLUME, volume))
        await self._wpctl("set-volume", SINK, f"{volume:.2f}")

    async def toggle_mute(self) -> None:
        await self._wpctl("set-mute", SINK, "toggle")

    async def default_sink_name(self) -> str | None:
        out = await self._wpctl("inspect", SINK)
        if not out:
            return None
        match = re.search(r'node\.description = "([^"]+)"', out)
        return match.group(1) if match else None
