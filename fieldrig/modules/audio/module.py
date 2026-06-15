"""Audio module: PipeWire + Bluetooth + MPRIS + waveform + channels.

Polls player/volume state and emits:
  audio_update      {source, title, artist, status, volume, ...}
  bluetooth_update  {devices: [...], connected: ...}
plus waveform_update / audio_channels_update from its components.
"""

import asyncio
from dataclasses import asdict
from typing import Any

from ...config import (
    BT_DISCOVERABLE_SECONDS,
    BT_POLL_EVERY_N_TICKS,
    MPRIS_POLL_SECONDS,
    VOLUME_STEP,
)
from ...core.module import Module
from ...core.events import EventBus
from ...logging_setup import get_module_logger
from .bluetooth import Bluetooth, BTDevice, PairingAgent
from .channels import AudioChannelManager
from .mpris import MPRIS
from .pipewire import PipeWire
from .waveform import WaveformAnalyzer

log = get_module_logger("audio")


class AudioModule(Module):
    name = "audio"

    def __init__(self, bus: EventBus) -> None:
        super().__init__(bus)
        self.pw = PipeWire()
        self.bt = Bluetooth()
        self.agent = PairingAgent(bus)
        self.mpris = MPRIS()
        self.waveform = WaveformAnalyzer(bus)
        self.channels = AudioChannelManager(bus, self.pw)
        self._task: asyncio.Task | None = None
        self._state: dict[str, Any] = {}
        self._bt_devices: list[BTDevice] = []
        bus.subscribe("power_loss", self._on_power_loss)
        bus.subscribe("bluetooth_paired", self._on_paired)

    # --- lifecycle ------------------------------------------------------

    async def start(self) -> None:
        await self.channels.start()
        await self.agent.start()
        self.waveform.start()
        await self._poll_once()
        self._task = asyncio.create_task(self._poll_loop())
        log.info("audio module up (pipewire=%s bluetooth=%s agent=%s mpris=%s waveform=%s)",
                 self.pw.available, self.bt.available, self.agent.active,
                 self.mpris.available, self.waveform.mode)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self.agent.stop()
        self.waveform.stop()

    async def status(self) -> dict[str, Any]:
        return {
            "pipewire": self.pw.available,
            "bluetooth": self.bt.available,
            "pairing_agent": self.agent.active,
            "mpris": self.mpris.available,
            "waveform": self.waveform.mode,
            "channels_active": sorted(self.channels.active),
        }

    async def ui_data(self) -> dict[str, Any]:
        return dict(self._state)

    def _on_power_loss(self, event: str, data: Any) -> None:
        log.info("power loss: audio state saved")

    async def _on_paired(self, event: str, data: Any) -> None:
        await self.bt_refresh("DEVICE PAIRED")

    # --- polling ----------------------------------------------------------

    async def _poll_loop(self) -> None:
        tick = 0
        while True:
            await asyncio.sleep(MPRIS_POLL_SECONDS)
            tick += 1
            try:
                await self._poll_once(with_bluetooth=tick % BT_POLL_EVERY_N_TICKS == 0)
            except Exception:
                log.exception("audio poll failed")

    async def _poll_once(self, with_bluetooth: bool = True) -> None:
        playing = await self.mpris.now_playing()
        volume = await self.pw.get_volume()

        if with_bluetooth and self.bt.available:
            self._bt_devices = await self.bt.devices()
            for device in self._bt_devices:
                # Trust anything that paired to us so the phone
                # reconnects on its own next drive.
                if device.paired and not device.trusted:
                    await self.bt.trust(device.mac)
                    device.trusted = True
        connected = next((d for d in self._bt_devices if d.connected), None)

        # A phone streaming to the Pi shows up as a bluez MPRIS player
        # (via mpris-proxy); a connected phone with no local player
        # means the same thing without metadata.
        if (playing and "bluez" in playing["player"].lower()) or \
                (connected is not None and playing is None):
            source = "BLUETOOTH"
        else:
            source = "PI AUX"

        state = {
            "source": source,
            "player": playing["player"] if playing else None,
            "title": playing["title"] if playing else "",
            "artist": playing["artist"] if playing else "",
            "album": playing["album"] if playing else "",
            "status": playing["status"] if playing else "Stopped",
            "position": playing["position"] if playing else None,
            "length": playing["length"] if playing else None,
            "volume": volume[0] if volume else self.channels.user_volume,
            "muted": volume[1] if volume else False,
            "bt_connected": connected is not None,
            "bt_device": connected.name if connected else None,
        }
        self.waveform.set_playing(state["status"] == "Playing")
        if state != self._state:
            self._state = state
            self.bus.emit("audio_update", state)

    # --- media controls (called by UI) ------------------------------------

    async def play_pause(self) -> None:
        await self.mpris.play_pause()
        await self._poll_once(with_bluetooth=False)

    async def next_track(self) -> None:
        await self.mpris.next_track()
        await self._poll_once(with_bluetooth=False)

    async def previous_track(self) -> None:
        await self.mpris.previous_track()
        await self._poll_once(with_bluetooth=False)

    async def volume_up(self) -> None:
        await self.channels.set_user_volume(self.channels.user_volume + VOLUME_STEP)
        await self._poll_once(with_bluetooth=False)

    async def volume_down(self) -> None:
        await self.channels.set_user_volume(self.channels.user_volume - VOLUME_STEP)
        await self._poll_once(with_bluetooth=False)

    async def toggle_mute(self) -> None:
        await self.pw.toggle_mute()
        await self._poll_once(with_bluetooth=False)

    # --- bluetooth management (called by UI) -------------------------------

    def _emit_bt(self, message: str = "") -> None:
        self.bus.emit("bluetooth_update", {
            "devices": [asdict(d) | {"flags": d.flags} for d in self._bt_devices],
            "message": message,
        })

    async def bt_refresh(self, message: str = "") -> None:
        self._bt_devices = await self.bt.devices()
        self._emit_bt(message)

    async def bt_pairing_mode(self) -> None:
        """Make the Pi discoverable so a phone can pair to it."""
        if not self.agent.active:
            self._emit_bt("PAIRING AGENT NOT RUNNING")
            return
        await self.agent.set_discoverable(True)
        await self.bt_refresh(
            f"PAIRING MODE — PICK '{self.agent.alias}' ON YOUR PHONE "
            f"({BT_DISCOVERABLE_SECONDS}s)"
        )

    async def bt_connect(self, mac: str) -> None:
        ok, msg = await self.bt.connect(mac)
        if ok:
            self.bus.emit("bluetooth_connected", {"mac": mac})
        await self.bt_refresh(msg)

    async def bt_disconnect(self, mac: str) -> None:
        _, msg = await self.bt.disconnect(mac)
        await self.bt_refresh(msg)

    async def bt_remove(self, mac: str) -> None:
        _, msg = await self.bt.remove(mac)
        await self.bt_refresh(msg)
