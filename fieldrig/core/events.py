"""Async pub/sub event bus.

Modules emit events ("gps_update", "bluetooth_connected", ...); the UI
subscribes and updates automatically. No polling in the UI layer.

Handlers take (event_name, data). Subscribing to "*" receives everything.
Hardware threads (pyudev, PyAudio) must use emit_threadsafe.
"""

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable

log = logging.getLogger("fieldrig.events")

Handler = Callable[[str, Any], Any]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the running loop so emit_threadsafe can hop into it."""
        self._loop = loop

    def subscribe(self, event: str, handler: Handler) -> Callable[[], None]:
        """Register a handler; returns an unsubscribe function."""
        self._subs[event].append(handler)

        def unsubscribe() -> None:
            try:
                self._subs[event].remove(handler)
            except ValueError:
                pass

        return unsubscribe

    def emit(self, event: str, data: Any = None) -> None:
        for handler in list(self._subs[event]) + list(self._subs["*"]):
            try:
                result = handler(event, data)
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)
            except Exception:
                log.exception("handler failed for event %r", event)

    def emit_threadsafe(self, event: str, data: Any = None) -> None:
        """Emit from a non-asyncio thread."""
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self.emit, event, data)
        else:
            self.emit(event, data)
