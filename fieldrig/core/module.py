"""Module API. Every hardware module follows this contract."""

from abc import ABC, abstractmethod
from typing import Any

from .events import EventBus


class Module(ABC):
    name = "Unknown"

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.running = False

    @abstractmethod
    async def start(self) -> None:
        """Bring the module up. Must be safe when hardware is absent."""

    @abstractmethod
    async def stop(self) -> None:
        """Tear down cleanly (tasks cancelled, devices released)."""

    @abstractmethod
    async def status(self) -> dict[str, Any]:
        """Health snapshot for the system screen / --check."""

    @abstractmethod
    async def ui_data(self) -> dict[str, Any]:
        """Current state for screens that mount after events fired."""
