"""Rolling feed of interesting bus events on the dashboard.

Subscribes to "*" and keeps the last few lifecycle events — modules
coming up, Bluetooth pairing/connecting, hardware hotplug, power —
while filtering the high-frequency streams (waveform, audio polls).
"""

from collections import deque
from datetime import datetime

from textual.widgets import Static

NOISY = {"waveform_update", "audio_update", "audio_channels_update",
         "bluetooth_update", "obd_update", "gps_update"}


class EventFeed(Static):
    def __init__(self, lines: int = 4, **kwargs) -> None:
        super().__init__(**kwargs)
        self._lines: deque[str] = deque(maxlen=lines)

    def on_mount(self) -> None:
        self._unsub = self.app.bus.subscribe("*", self._on_event)
        self._lines.append(self._fmt("ui_ready", None))
        self._redraw()

    def on_unmount(self) -> None:
        self._unsub()

    @staticmethod
    def _fmt(event: str, data) -> str:
        stamp = datetime.now().strftime("%H:%M:%S")
        detail = ""
        if isinstance(data, dict):
            detail = data.get("name") or data.get("model") or data.get("mac") or ""
            if detail:
                detail = f" [#008f25]{detail}[/]"
        return f"[#006618]{stamp}[/] {event}{detail}"

    def _on_event(self, event: str, data) -> None:
        if event in NOISY:
            return
        self._lines.append(self._fmt(event, data))
        self._redraw()

    def _redraw(self) -> None:
        self.update("\n".join(self._lines))
