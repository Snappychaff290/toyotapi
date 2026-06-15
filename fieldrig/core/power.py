"""Ignition power monitor.

Watches a GPIO pin wired (through a divider) to switched 12V. When the
ignition cuts, emits power_loss so modules can save state, then runs a
graceful shutdown -- but only if FIELDRIG_ENABLE_SHUTDOWN=1, so a loose
sense wire or a dev box never gets powered off by accident.

Without the gpiod library (dev machines) this stays inactive.
"""

import asyncio
import subprocess

from ..config import (
    IGNITION_GPIO_PIN,
    POWER_LOSS_DEBOUNCE_SECONDS,
    SHUTDOWN_GRACE_SECONDS,
    ENABLE_SHUTDOWN,
)
from ..logging_setup import get_module_logger
from .events import EventBus

log = get_module_logger("power")


class PowerMonitor:
    def __init__(self, bus: EventBus, pin: int = IGNITION_GPIO_PIN) -> None:
        self.bus = bus
        self.pin = pin
        self.active = False
        self._task: asyncio.Task | None = None
        self._request = None

    async def start(self) -> bool:
        try:
            import gpiod
            from gpiod.line import Direction
        except ImportError:
            log.info("gpiod not available; power monitoring disabled")
            return False
        try:
            self._request = gpiod.request_lines(
                "/dev/gpiochip0",
                consumer="fieldrig-power",
                config={self.pin: gpiod.LineSettings(direction=Direction.INPUT)},
            )
        except Exception:
            log.exception("could not claim GPIO %d", self.pin)
            return False
        self.active = True
        self._task = asyncio.create_task(self._watch())
        log.info("power monitor watching GPIO %d", self.pin)
        return True

    async def _watch(self) -> None:
        from gpiod.line import Value

        low_since: float | None = None
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(0.5)
            try:
                value = self._request.get_value(self.pin)
            except Exception:
                log.exception("GPIO read failed; power monitor stopping")
                return
            if value == Value.ACTIVE:
                low_since = None
                continue
            now = loop.time()
            if low_since is None:
                low_since = now
            elif now - low_since >= POWER_LOSS_DEBOUNCE_SECONDS:
                await self._on_power_loss()
                return

    async def _on_power_loss(self) -> None:
        log.warning("ignition power lost; starting graceful shutdown")
        # Modules save state / close / sync in their power_loss handlers.
        self.bus.emit("power_loss", {"grace_seconds": SHUTDOWN_GRACE_SECONDS})
        await asyncio.sleep(SHUTDOWN_GRACE_SECONDS)
        self.bus.emit("shutdown_imminent", None)
        if ENABLE_SHUTDOWN:
            subprocess.Popen(["sudo", "shutdown", "now"])
        else:
            log.warning("FIELDRIG_ENABLE_SHUTDOWN not set; skipping shutdown")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if self._request is not None:
            self._request.release()
            self._request = None
        self.active = False
