"""Module manager: registration, lifecycle, status aggregation.

Emits module_started / module_stopped / module_error on the bus.
"""

from typing import Any

from ..logging_setup import get_module_logger
from .events import EventBus
from .module import Module

log = get_module_logger("core")


class ModuleManager:
    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self._modules: dict[str, Module] = {}

    def register(self, module: Module) -> None:
        self._modules[module.name] = module
        log.info("registered module %r", module.name)

    def get(self, name: str) -> Module | None:
        return self._modules.get(name)

    @property
    def modules(self) -> dict[str, Module]:
        return dict(self._modules)

    async def start(self, name: str) -> bool:
        module = self._modules[name]
        if module.running:
            return True
        try:
            await module.start()
            module.running = True
            log.info("module %r started", name)
            self.bus.emit("module_started", {"name": name})
            return True
        except Exception as exc:
            log.exception("module %r failed to start", name)
            self.bus.emit("module_error", {"name": name, "error": str(exc)})
            return False

    async def stop(self, name: str) -> None:
        module = self._modules[name]
        if not module.running:
            return
        try:
            await module.stop()
        except Exception as exc:
            log.exception("module %r failed to stop", name)
            self.bus.emit("module_error", {"name": name, "error": str(exc)})
        finally:
            module.running = False
            self.bus.emit("module_stopped", {"name": name})

    async def start_all(self) -> None:
        for name in self._modules:
            await self.start(name)

    async def stop_all(self) -> None:
        for name in reversed(list(self._modules)):
            await self.stop(name)

    async def statuses(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for name, module in self._modules.items():
            try:
                out[name] = {"running": module.running, **await module.status()}
            except Exception as exc:
                out[name] = {"running": module.running, "error": str(exc)}
        return out
