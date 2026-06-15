"""MPRIS media player control via busctl (systemd's D-Bus CLI).

Sees any MPRIS player on the session bus: local players on the Pi, and
the phone over Bluetooth AVRCP once mpris-proxy (bluez-utils) is running
-- the setup scripts enable it as a user service.
"""

import asyncio
import json
import shutil
from typing import Any

from ...logging_setup import get_module_logger

log = get_module_logger("audio")

PLAYER_PREFIX = "org.mpris.MediaPlayer2."
OBJECT_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"


def _unwrap(obj: Any) -> Any:
    """Collapse busctl's {"type": ..., "data": ...} JSON envelopes."""
    if isinstance(obj, dict):
        if set(obj.keys()) == {"type", "data"}:
            return _unwrap(obj["data"])
        return {key: _unwrap(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_unwrap(item) for item in obj]
    return obj


class MPRIS:
    def __init__(self) -> None:
        self.available = shutil.which("busctl") is not None
        if not self.available:
            log.info("busctl not found; media control disabled")

    async def _busctl(self, *args: str, parse: bool = True,
                      timeout: float = 5.0) -> Any:
        if not self.available:
            return None
        cmd = ["busctl", "--user"]
        if parse:
            cmd.append("--json=short")
        cmd += list(args)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout)
            if proc.returncode != 0:
                return None
            if not parse:
                return True
            return json.loads(stdout.decode())
        except (asyncio.TimeoutError, OSError, json.JSONDecodeError):
            return None

    async def players(self) -> list[str]:
        result = await self._busctl(
            "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
            "org.freedesktop.DBus", "ListNames",
        )
        if not result:
            return []
        names = _unwrap(result.get("data", [[]]))[0]
        return [n for n in names if n.startswith(PLAYER_PREFIX)]

    async def _get_prop(self, player: str, prop: str) -> Any:
        result = await self._busctl(
            "call", player, OBJECT_PATH,
            "org.freedesktop.DBus.Properties", "Get",
            "ss", PLAYER_IFACE, prop,
        )
        if not result:
            return None
        data = result.get("data")
        return _unwrap(data[0]) if data else None

    async def now_playing(self) -> dict[str, Any] | None:
        """Metadata + playback state of the first available player."""
        players = await self.players()
        if not players:
            return None
        player = players[0]
        meta = await self._get_prop(player, "Metadata") or {}
        status = await self._get_prop(player, "PlaybackStatus") or "Stopped"
        position = await self._get_prop(player, "Position")  # microseconds

        artist = meta.get("xesam:artist")
        if isinstance(artist, list):
            artist = ", ".join(artist)
        return {
            "player": player.removeprefix(PLAYER_PREFIX),
            "title": meta.get("xesam:title") or "",
            "artist": artist or "",
            "album": meta.get("xesam:album") or "",
            "status": status,
            "position": position if isinstance(position, int) else None,
            "length": meta.get("mpris:length"),
        }

    async def _call_player(self, method: str, player: str | None = None) -> bool:
        if player is None:
            players = await self.players()
            if not players:
                return False
            player = players[0]
        result = await self._busctl(
            "call", player, OBJECT_PATH, PLAYER_IFACE, method, parse=False,
        )
        return bool(result)

    async def play_pause(self, player: str | None = None) -> bool:
        return await self._call_player("PlayPause", player)

    async def next_track(self, player: str | None = None) -> bool:
        return await self._call_player("Next", player)

    async def previous_track(self, player: str | None = None) -> bool:
        return await self._call_player("Previous", player)
