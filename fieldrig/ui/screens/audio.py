"""Audio screen: source + volume panels, now playing, transport rail."""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, Static

from ..widgets import NowPlaying, WaveformDisplay
from .base import FrameScreen

VOLUME_SEGMENTS = 20


class AudioScreen(FrameScreen):
    TITLE_TEXT = "AUDIO"
    NAV_KEY = "audio"

    def compose_body(self) -> ComposeResult:
        with Horizontal(id="audio-top"):
            source = Vertical(id="audio-source-panel", classes="panel")
            source.border_title = "SOURCE"
            with source:
                yield Static("--", id="audio-source-value")
                yield Static("", id="audio-bt-line", classes="dim")
            volume = Vertical(id="audio-volume-panel", classes="panel")
            volume.border_title = "VOLUME"
            with volume:
                yield Static("", id="audio-volume-meter")
                yield Static("", id="audio-volume-state", classes="dim")

        panel = Container(id="audio-np-panel", classes="panel")
        panel.border_title = "♪ NOW PLAYING"
        with panel:
            yield NowPlaying()
            yield WaveformDisplay()

        with Horizontal(id="audio-controls"):
            yield Button("◀◀", id="ctl-prev", classes="transport")
            yield Button("▶ ⏸", id="ctl-play", classes="transport accent")
            yield Button("▶▶", id="ctl-next", classes="transport")
            yield Static(classes="ctl-spacer")
            yield Button("VOL−", id="ctl-voldown")
            yield Button("VOL+", id="ctl-volup")
            yield Button("MUTE", id="ctl-mute")
            yield Static(classes="ctl-spacer")
            yield Button("⛉ PAIR", id="ctl-bt", classes="accent")

    def on_mount(self) -> None:
        self._unsub = self.app.bus.subscribe("audio_update", self._on_audio)
        self._on_audio("audio_update", getattr(self.app, "audio_state", {}))

    def on_unmount(self) -> None:
        self._unsub()

    def _on_audio(self, event: str, state) -> None:
        state = state or {}
        self.query_one("#audio-source-value", Static).update(
            state.get("source", "--")
        )
        if state.get("bt_connected"):
            bt_line = f"⛉ {state.get('bt_device') or 'PHONE'} LINKED"
        else:
            bt_line = "⛉ NO PHONE LINKED"
        self.query_one("#audio-bt-line", Static).update(bt_line)

        volume = state.get("volume", 0.0) or 0.0
        filled = round(min(1.0, volume) * VOLUME_SEGMENTS)
        meter = "█" * filled + "░" * (VOLUME_SEGMENTS - filled)
        self.query_one("#audio-volume-meter", Static).update(
            f"{meter} {round(volume * 100):>3}%"
        )
        self.query_one("#audio-volume-state", Static).update(
            "[#ff4141]◼ MUTED[/]" if state.get("muted") else "◻ LIVE"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "ctl-prev": self.app.audio.previous_track,
            "ctl-play": self.app.audio.play_pause,
            "ctl-next": self.app.audio.next_track,
            "ctl-voldown": self.app.audio.volume_down,
            "ctl-volup": self.app.audio.volume_up,
            "ctl-mute": self.app.audio.toggle_mute,
        }
        button_id = event.button.id or ""
        if button_id == "ctl-bt":
            event.stop()
            self.app.push_screen("bluetooth")
        elif button_id in actions:
            event.stop()
            self.run_worker(actions[button_id](), exclusive=False)
