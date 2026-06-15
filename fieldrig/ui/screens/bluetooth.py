"""Bluetooth management.

The Pi is the head unit: phones pair *to* it. PAIR MODE makes the Pi
discoverable as "FieldRig"; the pairing agent accepts the phone's
request automatically and the device shows up in the list below.
"""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, Label, ListItem, ListView, Static

from ...config import BT_ALIAS
from .base import FrameScreen


class BluetoothScreen(FrameScreen):
    TITLE_TEXT = "BLUETOOTH"
    NAV_KEY = "audio"

    def compose_body(self) -> ComposeResult:
        pairing = Vertical(id="bt-pairing-panel", classes="panel")
        pairing.border_title = "⛉ PAIRING"
        with pairing:
            yield Static(
                f"[#008f25]PHONES PAIR TO THE PI — TAP [bold]PAIR MODE[/bold], "
                f"THEN PICK '{BT_ALIAS}' ON YOUR PHONE[/]",
                id="bt-hint",
            )
            yield Static("READY", id="bt-status")
        devices = Container(id="bt-devices-panel", classes="panel")
        devices.border_title = "KNOWN DEVICES"
        devices.border_subtitle = "TAP TO SELECT"
        with devices:
            yield ListView(id="bt-list")
        with Horizontal(id="bt-actions"):
            yield Button("⛉ PAIR MODE", id="bt-pairmode", classes="accent")
            yield Button("CONNECT", id="bt-connect")
            yield Button("DISCONN", id="bt-disconnect")
            yield Button("REMOVE", id="bt-remove")
            yield Static(classes="ctl-spacer")
            yield Button("← BACK", id="nav-back")

    def on_mount(self) -> None:
        self._devices: list[dict] = []
        self._unsub = self.app.bus.subscribe("bluetooth_update", self._on_bt_update)
        if not self.app.audio.bt.available:
            self._set_status("BLUETOOTH UNAVAILABLE (bluetoothctl not found)")
        else:
            self.run_worker(self.app.audio.bt_refresh(), exclusive=False)

    def on_unmount(self) -> None:
        self._unsub()

    def _set_status(self, text: str) -> None:
        self.query_one("#bt-status", Static).update(text)

    def _on_bt_update(self, event: str, data) -> None:
        data = data or {}
        self._devices = data.get("devices", [])
        if data.get("message"):
            self._set_status(data["message"])
        list_view = self.query_one("#bt-list", ListView)
        index = list_view.index
        list_view.clear()
        for device in self._devices:
            if device["connected"]:
                row = (f"[bold]◉ {device['name']:<26}[/bold] "
                       f"[#008f25]{device['mac']}[/]  [{device['flags']}]")
            else:
                row = (f"[#00b22d]○ {device['name']:<26}[/] "
                       f"[#008f25]{device['mac']}  [{device['flags']}][/]")
            list_view.append(ListItem(Label(row)))
        if self._devices:
            list_view.index = min(index or 0, len(self._devices) - 1)

    def _selected_mac(self) -> str | None:
        index = self.query_one("#bt-list", ListView).index
        if index is None or not (0 <= index < len(self._devices)):
            return None
        return self._devices[index]["mac"]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if not button_id.startswith("bt-"):
            return  # nav-back bubbles up to the app
        event.stop()
        audio = self.app.audio
        if button_id == "bt-pairmode":
            self.run_worker(audio.bt_pairing_mode(), exclusive=True)
            return
        mac = self._selected_mac()
        if mac is None:
            self._set_status("SELECT A DEVICE FIRST")
            return
        action = {
            "bt-connect": audio.bt_connect,
            "bt-disconnect": audio.bt_disconnect,
            "bt-remove": audio.bt_remove,
        }.get(button_id)
        if action is not None:
            self._set_status(f"{button_id.removeprefix('bt-').upper()} {mac}...")
            self.run_worker(action(mac), exclusive=True)
