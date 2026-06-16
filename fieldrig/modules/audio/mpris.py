"""MPRIS media player control over D-Bus (event-driven).

Sees any MPRIS player on the session bus: local players on the Pi, and the
phone over Bluetooth AVRCP once mpris-proxy (bluez-utils) is running -- the
setup scripts enable it as a user service.

This is push-based. It holds one persistent D-Bus connection, binds to the
active player, and fires `on_change` the instant PlaybackStatus or Metadata
changes -- so the UI reacts in well under a tenth of a second instead of
waiting for a poll. NameOwnerChanged is watched so we rebind when the phone
connects/disconnects or a local player starts/quits.

Two things are deliberately left to the rest of the stack: the audio module
still runs a slow reconcile poll (a heartbeat that corrects drift and catches
any missed signal), and the progress bar is interpolated client-side because
MPRIS, by spec, does not emit Position changes. Falls back to a no-op
(available=False) if dbus-fast or the session bus is missing, so dev machines
and a busless boot degrade gracefully -- same contract as the old busctl path.
"""

import asyncio
from typing import Any, Callable

from ...logging_setup import get_module_logger

log = get_module_logger("audio")

try:
    from dbus_fast import BusType, Variant
    from dbus_fast.aio import MessageBus
    _HAVE_DBUS = True
except ImportError:  # dev box without the dep, or no D-Bus python libs
    _HAVE_DBUS = False

PLAYER_PREFIX = "org.mpris.MediaPlayer2."
OBJECT_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
DBUS_NAME = "org.freedesktop.DBus"
DBUS_PATH = "/org/freedesktop/DBus"


def _val(v: Any) -> Any:
    """Unwrap a dbus-fast Variant (Metadata map values arrive wrapped)."""
    return v.value if isinstance(v, Variant) else v


class MPRIS:
    def __init__(self) -> None:
        self.available = _HAVE_DBUS
        # Set by the audio module; called (no args) on every playback change.
        self.on_change: Callable[[], Any] | None = None
        self._bus = None
        self._dbus = None             # org.freedesktop.DBus interface proxy
        self._player_name: str | None = None
        self._player = None           # bound player's Player iface (control)
        self._props = None            # bound player's Properties iface (signals)
        if not _HAVE_DBUS:
            log.info("dbus-fast not installed; media control disabled")

    # --- connection / binding ---------------------------------------------

    async def connect(self) -> None:
        """Open the session bus, watch for players, and bind the first one."""
        if not self.available:
            return
        try:
            self._bus = await MessageBus(bus_type=BusType.SESSION).connect()
            intro = await self._bus.introspect(DBUS_NAME, DBUS_PATH)
            obj = self._bus.get_proxy_object(DBUS_NAME, DBUS_PATH, intro)
            self._dbus = obj.get_interface(DBUS_NAME)
            self._dbus.on_name_owner_changed(self._on_name_owner_changed)
            await self._bind_first_player()
        except Exception as e:
            log.info("no session bus; media control disabled (%s)", e)
            self.available = False

    async def close(self) -> None:
        if self._bus is not None:
            try:
                self._bus.disconnect()
            except Exception:
                pass
            self._bus = None

    def _on_name_owner_changed(self, name: str, old: str, new: str) -> None:
        if name.startswith(PLAYER_PREFIX):
            asyncio.ensure_future(self._rebind(name, vanished=(new == "")))

    async def _rebind(self, name: str, vanished: bool) -> None:
        if vanished:
            # If the player we were following went away, fall back to any other.
            if name == self._player_name:
                self._unbind()
                await self._bind_first_player()
        elif self._player_name is None:
            # A player appeared and we had none -- adopt it.
            await self._bind_first_player()
        self._notify()

    async def _bind_first_player(self) -> None:
        names = await self._dbus.call_list_names()
        players = sorted(n for n in names if n.startswith(PLAYER_PREFIX))
        if players:
            await self._bind(players[0])
        else:
            self._unbind()

    async def _bind(self, name: str) -> None:
        try:
            intro = await self._bus.introspect(name, OBJECT_PATH)
            obj = self._bus.get_proxy_object(name, OBJECT_PATH, intro)
            # Properties is the read + signal path and is always present.
            # Bind it first so metadata works even if the Player iface below
            # can't be created. We read state through Properties, not through
            # the Player iface, precisely so a quirky player can't break it.
            self._props = obj.get_interface(PROPS_IFACE)
            self._props.on_properties_changed(self._on_props_changed)
            # The Player iface (control: play/pause/next) may be under-declared
            # in a bluez/mpris-proxy player's introspection -- tolerate it.
            try:
                self._player = obj.get_interface(PLAYER_IFACE)
            except Exception:
                self._player = None
                log.info("player %s exposes no Player iface; controls disabled",
                         name.removeprefix(PLAYER_PREFIX))
            self._player_name = name
            log.info("bound MPRIS player %s", name.removeprefix(PLAYER_PREFIX))
        except Exception:
            log.exception("could not bind MPRIS player %s", name)
            self._unbind()

    def _unbind(self) -> None:
        if self._props is not None:
            try:
                self._props.off_properties_changed(self._on_props_changed)
            except Exception:
                pass
        self._player = self._props = self._player_name = None

    def _on_props_changed(self, iface: str, changed: dict, invalid: list) -> None:
        if iface == PLAYER_IFACE:
            self._notify()

    def _notify(self) -> None:
        if self.on_change is None:
            return
        try:
            result = self.on_change()
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)
        except Exception:
            log.exception("mpris on_change handler failed")

    # --- reads / controls -------------------------------------------------

    async def now_playing(self) -> dict[str, Any] | None:
        """Live metadata + playback state of the bound player. Returns None
        when nothing is bound.

        Each property is fetched individually with Properties.Get -- the proven
        path from the old busctl implementation. bluez/mpris-proxy players
        answer per-property Get reliably but commonly return an *empty* GetAll,
        which is what left the now-playing panel blank. We also don't use
        dbus-fast's introspection-generated getters, since those players tend
        to under-declare their properties in introspection."""
        if self._props is None:
            return None

        async def get(name: str) -> Any:
            try:
                return _val(await self._props.call_get(PLAYER_IFACE, name))
            except Exception:
                return None

        meta_raw = await get("Metadata")
        status = await get("PlaybackStatus")
        position = await get("Position")  # microseconds; many BT players omit it

        meta = {k: _val(v) for k, v in (meta_raw or {}).items()}
        artist = meta.get("xesam:artist")
        if isinstance(artist, list):
            artist = ", ".join(artist)
        return {
            "player": (self._player_name or "").removeprefix(PLAYER_PREFIX),
            "title": meta.get("xesam:title") or "",
            "artist": artist or "",
            "album": meta.get("xesam:album") or "",
            "status": status or "Stopped",
            "position": position if isinstance(position, int) else None,
            "length": meta.get("mpris:length"),
        }

    async def _call(self, method: str) -> bool:
        if self._player is None:
            return False
        try:
            await getattr(self._player, f"call_{method}")()
            return True
        except Exception:
            return False

    async def play_pause(self) -> bool:
        return await self._call("play_pause")

    async def next_track(self) -> bool:
        return await self._call("next")

    async def previous_track(self) -> bool:
        return await self._call("previous")
