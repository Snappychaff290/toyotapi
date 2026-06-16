"""Camera module: USB UVC capture card -> live MJPEG feed.

A watchdog loop keeps the capture card connected: it scans /dev/video* (or
the configured device), opens the first one that actually delivers frames,
and re-scans when the card is absent or drops. Plugging the card in wakes the
loop immediately via the hardware watcher. Emits:

  camera_update  {connected, device}

The frames themselves don't go over the event bus -- the server streams them
straight from the capture thread via mjpeg_stream() (see server/app.py and
the /camera.mjpg endpoint), which is the whole reason the UI is a browser
page and not a real terminal.
"""

import asyncio
import glob
import re
from typing import Any

from ...config import CAMERA_DEVICE, CAMERA_FPS, CAMERA_RECONNECT_SECONDS
from ...core.events import EventBus
from ...core.module import Module
from ...logging_setup import get_module_logger
from .capture import Camera

log = get_module_logger("camera")


def _candidate_indices() -> list[int]:
    """Video device indices to try, in order. Honours CAMERA_DEVICE; otherwise
    every /dev/videoN present (lowest first -- the USB card is usually video0
    on a headless Pi with no CSI camera)."""
    if CAMERA_DEVICE is not None:
        try:
            return [int(re.sub(r"\D", "", CAMERA_DEVICE) or CAMERA_DEVICE)]
        except ValueError:
            return []
    nodes = sorted(int(m.group(1))
                   for path in glob.glob("/dev/video*")
                   if (m := re.search(r"(\d+)$", path)))
    return nodes


class CameraModule(Module):
    name = "camera"

    def __init__(self, bus: EventBus) -> None:
        super().__init__(bus)
        self.camera = Camera()
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        bus.subscribe("hardware_added", self._on_hardware)

    # --- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        self._task = asyncio.create_task(self._watchdog())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await asyncio.to_thread(self.camera.close)

    async def status(self) -> dict[str, Any]:
        return {
            "opencv": self.camera.available,
            "connected": self.camera.connected,
            "device": self.camera.device,
        }

    async def ui_data(self) -> dict[str, Any]:
        return {"connected": self.camera.connected, "device": self.camera.device}

    def _on_hardware(self, event: str, data: Any) -> None:
        self._wake.set()

    # --- watchdog ---------------------------------------------------------

    async def _watchdog(self) -> None:
        while True:
            was_connected = self.camera.connected
            if not self.camera.connected:
                await self._try_open()
            if self.camera.connected != was_connected:
                self._emit()
            await self._sleep(CAMERA_RECONNECT_SECONDS)

    async def _try_open(self) -> None:
        for index in _candidate_indices():
            if await asyncio.to_thread(self.camera.open, index):
                return

    def _emit(self) -> None:
        self.bus.emit("camera_update", {
            "connected": self.camera.connected,
            "device": self.camera.device,
        })

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._wake.wait(), seconds)
        except asyncio.TimeoutError:
            pass
        self._wake.clear()

    # --- frame stream (consumed by the server's /camera.mjpg) -------------

    async def mjpeg_stream(self):
        """Yield multipart/x-mixed-replace JPEG chunks for as long as the card
        stays connected. Waits on the capture thread for each new frame instead
        of polling, so it never sends a frame twice and adds no latency."""
        boundary = b"--frame\r\n"
        last_id = -1
        timeout = max(2.0, 4.0 / max(1, CAMERA_FPS))
        while self.camera.connected:
            frame_id, jpeg = await asyncio.to_thread(
                self.camera.wait_frame, last_id, timeout)
            if jpeg is None or frame_id == last_id:
                continue
            last_id = frame_id
            yield (boundary
                   + b"Content-Type: image/jpeg\r\n"
                   + f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
                   + jpeg + b"\r\n")
