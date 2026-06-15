"""PyUdev USB hotplug watcher.

Emits hardware_added / hardware_removed with vendor/product info so
modules can react instantly (RTL-SDR plugged in -> SDR module activates).
No-op on machines without pyudev (dev boxes, WSL).
"""

from ..logging_setup import get_module_logger
from .events import EventBus

log = get_module_logger("hardware")


class HardwareWatcher:
    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self._observer = None
        self.active = False

    def start(self) -> bool:
        try:
            import pyudev
        except ImportError:
            log.info("pyudev not available; USB hotplug detection disabled")
            return False
        try:
            context = pyudev.Context()
            monitor = pyudev.Monitor.from_netlink(context)
            monitor.filter_by("usb")
            self._observer = pyudev.MonitorObserver(monitor, callback=self._on_event)
            self._observer.start()
            self.active = True
            log.info("USB hotplug watcher started")
            return True
        except Exception:
            log.exception("failed to start udev monitor")
            return False

    def _on_event(self, device) -> None:
        # Runs on the pyudev observer thread.
        info = {
            "action": device.action,
            "vendor_id": device.get("ID_VENDOR_ID"),
            "product_id": device.get("ID_MODEL_ID"),
            "model": device.get("ID_MODEL"),
        }
        event = "hardware_added" if device.action == "add" else "hardware_removed"
        log.info("%s: %s", event, info)
        self.bus.emit_threadsafe(event, info)

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer = None
        self.active = False
