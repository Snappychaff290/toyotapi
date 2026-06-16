"""OBD-II module: live vehicle telemetry + diagnostic trouble codes.

Drives an ELM327 USB dongle. A single loop reconnects when the adapter is
absent and polls live PIDs once a second when it's present, emitting:

  obd_update      {connected, speed_mph, rpm, fuel_pct, coolant_f, voltage}
  obd_dtc_update  {codes: [{code, desc}], message}

It activates the moment the dongle is plugged in: the hardware watcher's
hardware_added event nudges the loop out of its reconnect wait, so there's
no need to wait out the poll interval. Safe with no dongle attached -- the
loop just keeps scanning and the screen stays offline.
"""

import asyncio
from typing import Any

from ...config import OBD_POLL_SECONDS, OBD_RECONNECT_SECONDS
from ...core.events import EventBus
from ...core.module import Module
from ...logging_setup import get_module_logger
from .elm327 import Elm327

log = get_module_logger("obd")


class ObdModule(Module):
    name = "obd"

    def __init__(self, bus: EventBus) -> None:
        super().__init__(bus)
        self.elm = Elm327()
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._state: dict[str, Any] = {"connected": False}
        self._dtcs: list[dict[str, str]] = []
        # Plugging the dongle in (or any USB add) wakes the reconnect wait.
        bus.subscribe("hardware_added", self._on_hardware)

    # --- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await asyncio.to_thread(self.elm.close)

    async def status(self) -> dict[str, Any]:
        return {
            "obd_library": self.elm.available,
            "connected": self.elm.connected,
            "dtc_count": len(self._dtcs),
        }

    async def ui_data(self) -> dict[str, Any]:
        return {**self._state, "dtcs": list(self._dtcs)}

    def _on_hardware(self, event: str, data: Any) -> None:
        self._wake.set()

    # --- loop -------------------------------------------------------------

    async def _loop(self) -> None:
        while True:
            if self.elm.connected:
                await self._poll()
                await self._sleep(OBD_POLL_SECONDS)
            else:
                if await asyncio.to_thread(self.elm.connect):
                    await self._on_connect()
                else:
                    await self._sleep(OBD_RECONNECT_SECONDS)

    async def _sleep(self, seconds: float) -> None:
        """Sleep, but wake early if a USB device is plugged in."""
        try:
            await asyncio.wait_for(self._wake.wait(), seconds)
        except asyncio.TimeoutError:
            pass
        self._wake.clear()

    async def _on_connect(self) -> None:
        log.info("OBD-II link up")
        await self._poll()
        await self.refresh_dtcs()

    async def _poll(self) -> None:
        values = await asyncio.to_thread(self.elm.read_live)
        if values is None:
            await self._handle_disconnect()
            return
        state = {"connected": True, **values}
        if state != self._state:
            self._state = state
            self.bus.emit("obd_update", state)

    async def _handle_disconnect(self) -> None:
        await asyncio.to_thread(self.elm.close)
        self._state = {"connected": False}
        self._dtcs = []
        self.bus.emit("obd_update", self._state)
        self.bus.emit("obd_dtc_update", {"codes": [], "message": "OFFLINE"})

    # --- commands (called by the server over /ws) -------------------------

    async def refresh_dtcs(self) -> None:
        if not self.elm.connected:
            self.bus.emit("obd_dtc_update", {"codes": [], "message": "OFFLINE"})
            return
        self._dtcs = await asyncio.to_thread(self.elm.read_dtcs)
        message = "NO CODES STORED" if not self._dtcs else f"{len(self._dtcs)} CODE(S) STORED"
        self.bus.emit("obd_dtc_update", {"codes": self._dtcs, "message": message})

    async def clear_dtcs(self) -> None:
        if not self.elm.connected:
            self.bus.emit("obd_dtc_update", {"codes": [], "message": "OFFLINE"})
            return
        ok = await asyncio.to_thread(self.elm.clear_dtcs)
        if ok:
            self._dtcs = []
            self.bus.emit("obd_dtc_update", {"codes": [], "message": "CODES CLEARED"})
        else:
            self.bus.emit("obd_dtc_update",
                          {"codes": self._dtcs, "message": "CLEAR FAILED"})
