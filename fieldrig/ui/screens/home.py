"""Home dashboard: now playing + waveform up top, telemetry gauges below.

Gauge cells show placeholders until the OBD module lands (Phase 4);
they already subscribe to obd_update so they light up the day it ships.
"""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static

from ..widgets import EventFeed, NowPlaying, SystemStats, WaveformDisplay
from .base import FrameScreen

TELEMETRY_CELLS = [
    ("speed", "SPEED", "MPH"),
    ("rpm", "RPM", "× 1000"),
    ("fuel", "FUEL", "% REMAINING"),
    ("temp", "COOLANT", "°F"),
]


class HomeScreen(FrameScreen):
    TITLE_TEXT = "HOME"
    NAV_KEY = "home"

    def compose_body(self) -> ComposeResult:
        panel = Container(id="now-playing-panel", classes="panel")
        panel.border_title = "♪ NOW PLAYING"
        panel.border_subtitle = "SOURCE --"
        with panel:
            yield NowPlaying()
            yield WaveformDisplay()
        with Horizontal(id="telemetry"):
            for key, label, unit in TELEMETRY_CELLS:
                cell = Vertical(classes="telemetry-cell panel")
                cell.border_title = label
                with cell:
                    yield Static("---", id=f"telemetry-{key}",
                                 classes="telemetry-value")
                    yield Static(f"[#006618]{unit}[/]", classes="telemetry-unit")
        with Horizontal(id="home-bottom"):
            stats = Container(id="system-panel", classes="panel")
            stats.border_title = "⚙ SYSTEM"
            with stats:
                yield SystemStats()
            feed = Container(id="event-panel", classes="panel")
            feed.border_title = "◍ EVENT FEED"
            feed.border_subtitle = "BUS"
            with feed:
                yield EventFeed()

    def on_mount(self) -> None:
        self._unsubs = [
            self.app.bus.subscribe("obd_update", self._on_obd),
            self.app.bus.subscribe("audio_update", self._on_audio),
        ]
        self._on_audio("audio_update", getattr(self.app, "audio_state", {}))

    def on_unmount(self) -> None:
        for unsub in self._unsubs:
            unsub()

    def _on_audio(self, event: str, state) -> None:
        state = state or {}
        source = state.get("source", "--")
        volume = round((state.get("volume") or 0.0) * 100)
        self.query_one("#now-playing-panel").border_subtitle = (
            f"SOURCE {source} · VOL {volume}%"
        )

    def _on_obd(self, event: str, data) -> None:
        data = data or {}
        for key, _, _ in TELEMETRY_CELLS:
            if key in data:
                self.query_one(f"#telemetry-{key}", Static).update(str(data[key]))
