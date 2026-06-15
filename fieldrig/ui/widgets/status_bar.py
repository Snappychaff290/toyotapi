"""Top status strip: module chips left, source/voltage/clock right.

Chips light up (inverse video) as their modules come online. GPS, MESH,
SDR, OBD stay dark until their phases land; BT tracks live state from
the audio module. Voltage arrives with OBD in Phase 4.
"""

from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

CHIP_MODULES = ("GPS", "MESH", "BT", "SDR", "OBD")


def _chip(label: str, on: bool) -> str:
    if on:
        return f"[#0d0d0d on #00ff41 bold] {label} [/]"
    return f"[#006618 on #001a00] {label} [/]"


class StatusBar(Horizontal):
    def compose(self) -> ComposeResult:
        yield Static(id="status-chips")
        yield Static(id="status-right")

    def on_mount(self) -> None:
        self._audio_state: dict = getattr(self.app, "audio_state", {}) or {}
        self._unsub = self.app.bus.subscribe("audio_update", self._on_audio)
        self.set_interval(1.0, self._refresh)
        self._refresh()

    def on_unmount(self) -> None:
        self._unsub()

    def _on_audio(self, event: str, data) -> None:
        self._audio_state = data or {}
        self._refresh()

    def _refresh(self) -> None:
        state = {"BT": bool(self._audio_state.get("bt_connected"))}
        chips = " ".join(_chip(m, state.get(m, False)) for m in CHIP_MODULES)
        self.query_one("#status-chips", Static).update(chips)

        source = "BT" if self._audio_state.get("source") == "BLUETOOTH" else "AUX"
        clock = datetime.now().strftime("%H:%M")
        self.query_one("#status-right", Static).update(
            f"[#00d938]♪ {source}[/]  [#008f25]⚡ --.-V[/]  [bold]{clock}[/]"
        )
