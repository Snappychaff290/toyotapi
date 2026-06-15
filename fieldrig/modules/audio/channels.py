"""Audio channel manager.

Logical channels with priorities; music ducks automatically while a
higher-priority channel (navigation voice, alerts) is active, and
recovers when it ends. Alerts override everything.

In Phase 3 music is the only real source on the sink, so ducking is
applied as a gain on the default sink relative to the user's volume.
Later phases route per-stream once nav/radio streams exist.
"""

from ...config import MAX_VOLUME
from ...core.events import EventBus
from ...logging_setup import get_module_logger
from .pipewire import PipeWire

log = get_module_logger("audio")

CHANNEL_PRIORITIES = {
    "alerts": 100,
    "navigation": 80,
    "notification": 60,
    "radio": 40,
    "music": 40,
}

# What the music channel ducks to while each channel is active.
DUCK_MUSIC_TO = {
    "alerts": 0.15,
    "navigation": 0.30,
    "notification": 0.60,
}


class AudioChannelManager:
    def __init__(self, bus: EventBus, pipewire: PipeWire) -> None:
        self.bus = bus
        self.pw = pipewire
        self.active: set[str] = set()
        self.user_volume = 0.8

    async def start(self) -> None:
        current = await self.pw.get_volume()
        if current is not None:
            self.user_volume = min(MAX_VOLUME, current[0])

    @property
    def music_gain(self) -> float:
        """Hardest duck wins when several channels are speaking."""
        return min(
            (DUCK_MUSIC_TO[name] for name in self.active if name in DUCK_MUSIC_TO),
            default=1.0,
        )

    async def activate(self, name: str) -> None:
        if name not in CHANNEL_PRIORITIES:
            log.warning("unknown audio channel %r", name)
            return
        self.active.add(name)
        await self._apply()

    async def deactivate(self, name: str) -> None:
        self.active.discard(name)
        await self._apply()

    async def set_user_volume(self, volume: float) -> None:
        self.user_volume = max(0.0, min(MAX_VOLUME, volume))
        await self._apply()

    async def _apply(self) -> None:
        await self.pw.set_volume(self.user_volume * self.music_gain)
        self.bus.emit("audio_channels_update", {
            "active": sorted(self.active),
            "music_gain": self.music_gain,
            "user_volume": self.user_volume,
        })
