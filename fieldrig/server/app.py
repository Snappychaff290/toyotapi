"""FieldRig web server.

The visible UI is a fullscreen Chromium kiosk styled like a terminal;
this server owns the actual machine: core engine + modules run here,
bus events fan out to the page over /ws as JSON, commands come back on
the same socket, and /api/state gives late-joining clients a snapshot.

This split is what makes later phases possible in a way a real TUI
isn't: Phase 8's camera becomes an MJPEG stream rendered by an <img>
tag, Phase 5's maps are MapLibre GL JS against local MBTiles tiles.
"""

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

REPO_DIR = Path(__file__).resolve().parents[2]

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..config import BT_DISCOVERABLE_SECONDS
from ..core import EventBus, ModuleManager
from ..core.hardware import HardwareWatcher
from ..core.power import PowerMonitor
from ..core.sysinfo import sysinfo_task
from ..logging_setup import get_module_logger, setup_logging
from ..modules.audio import AudioModule
from ..modules.camera import CameraModule
from ..modules.obd import ObdModule

log = get_module_logger("server")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# Privileged helper that flips the root filesystem ro/rw (see setup/06).
FS_HELPER = "/usr/local/sbin/fieldrig-mount"


async def _run(*args: str, cwd: str | None = None,
               timeout: float = 120) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 1, "timed out"
    return proc.returncode or 0, (out or b"").decode(errors="replace").strip()


async def _root_is_readonly() -> bool:
    """True when / is mounted read-only (the sealed car state)."""
    _, opts = await _run("findmnt", "-no", "OPTIONS", "/")
    return "ro" in opts.split(",")


# Persisted UI settings (theme colour, ...). Lives in the user's home, so it
# survives reboots; writing it needs a read-write window under the sealed root.
SETTINGS_FILE = Path.home() / ".config" / "fieldrig" / "settings.json"

# A theme is four colour roles (accent/chrome/surface/muted), each a hue +
# saturation; the front end derives every CSS shade from them (see web/app.js).
THEME_ROLES = ("accent", "chrome", "surface", "muted")
DEFAULT_THEME = {
    "accent":  {"h": 135, "s": 100},
    "chrome":  {"h": 135, "s": 85},
    "surface": {"h": 135, "s": 12},
    "muted":   {"h": 135, "s": 40},
}


def _migrate_theme(t: Any) -> Any:
    """Upgrade the old single hue+sat theme to the four-role format, so a
    settings.json written by an earlier build still themes sensibly."""
    if isinstance(t, dict) and "accent" not in t and "h" in t:
        h = int(t["h"])
        s = max(0, min(100, int(str(t["s"]).rstrip("%"))))
        return {
            "accent":  {"h": h, "s": s},
            "chrome":  {"h": h, "s": max(0, s - 15)},
            "surface": {"h": h, "s": min(s, 12)},
            "muted":   {"h": h, "s": min(s, 40)},
        }
    return t


def _sanitize_theme(t: Any) -> dict:
    """Validate + clamp a four-role theme; these values are interpolated into
    CSS, so every role must end up a safe hue (0-360) + saturation (0-100)."""
    if not isinstance(t, dict):
        raise ValueError("theme must be an object")
    out = {}
    for role in THEME_ROLES:
        c = t.get(role) or {}
        out[role] = {
            "h": max(0, min(360, int(c["h"]))),
            "s": max(0, min(100, int(str(c["s"]).rstrip("%")))),
        }
    return out


def _load_theme() -> dict:
    try:
        t = json.loads(SETTINGS_FILE.read_text()).get("theme")
        return _sanitize_theme(_migrate_theme(t))
    except Exception:
        return {role: dict(c) for role, c in DEFAULT_THEME.items()}


def _load_rotation() -> int:
    """Saved screen rotation in degrees (0/90/180/270); 0 if unset/garbage."""
    try:
        deg = int(json.loads(SETTINGS_FILE.read_text()).get("rotation", 0))
        return deg if deg in (0, 90, 180, 270) else 0
    except Exception:
        return 0


async def _save_setting(key: str, value: Any) -> None:
    """Merge one key into the persisted settings file. Briefly remounts the
    root read-write if it's sealed (the car's normal state), then re-seals it."""
    was_readonly = await _root_is_readonly()
    if was_readonly:
        await _run("sudo", "-n", FS_HELPER, "rw")
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(SETTINGS_FILE.read_text())
        except Exception:
            data = {}
        data[key] = value
        SETTINGS_FILE.write_text(json.dumps(data))
    except OSError:
        log.warning("could not persist %s to %s", key, SETTINGS_FILE)
    finally:
        if was_readonly:
            await _run("sync")
            await _run("sudo", "-n", FS_HELPER, "ro")


class Hub:
    """Fans every bus event out to all connected websocket clients."""

    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    def broadcast(self, event: str, data: Any) -> None:
        if not self.clients:
            return
        try:
            message = json.dumps({"event": event, "data": data}, default=str)
        except TypeError:
            log.warning("unserializable event %r dropped", event)
            return
        for ws in list(self.clients):
            asyncio.ensure_future(self._send(ws, message))

    async def _send(self, ws: WebSocket, message: str) -> None:
        try:
            await ws.send_text(message)
        except Exception:
            self.clients.discard(ws)


def create_app() -> FastAPI:
    setup_logging()
    bus = EventBus()
    manager = ModuleManager(bus)
    audio = AudioModule(bus)
    obd = ObdModule(bus)
    camera = CameraModule(bus)
    manager.register(audio)
    manager.register(obd)
    manager.register(camera)
    hardware = HardwareWatcher(bus)
    power = PowerMonitor(bus)
    hub = Hub()
    bus.subscribe("*", hub.broadcast)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        bus.attach_loop(asyncio.get_running_loop())
        log.info("FieldRig server starting")
        await manager.start_all()
        hardware.start()
        await power.start()
        stats = asyncio.create_task(sysinfo_task(bus))
        yield
        stats.cancel()
        await power.stop()
        hardware.stop()
        await manager.stop_all()
        log.info("FieldRig server stopped")

    app = FastAPI(title="FieldRig", version=__version__, lifespan=lifespan)

    async def _pull_and_install(emit) -> bool:
        """Do the actual git pull + optional dep install. Returns True if new
        code landed and the service should restart. Assumes the filesystem is
        already writable (caller handles the read-only car state)."""
        _, before = await _run("git", "rev-parse", "HEAD", cwd=str(REPO_DIR))

        emit("pulling", "PULLING LATEST…")
        code, out = await _run("git", "pull", "--ff-only", cwd=str(REPO_DIR))
        if code != 0:
            # Distinguish "offline" from a real git error by the message git
            # prints, rather than pre-probing some host that may be blocked.
            low = out.lower()
            offline = ("could not resolve host", "temporary failure in name resolution",
                       "unable to access", "could not read from remote repository",
                       "network is unreachable", "no route to host",
                       "connection timed out", "connection refused", "timed out")
            if any(s in low for s in offline):
                emit("error", "NO INTERNET — UPDATE SKIPPED")
            else:
                tail = out.splitlines()[-1] if out else "error"
                emit("error", f"GIT PULL FAILED: {tail}")
            return False
        if "up to date" in out.lower():
            emit("uptodate", "ALREADY UP TO DATE")
            return False

        # If the pull touched dependency metadata, reinstall into the venv
        # before restarting — otherwise new packages would be missing.
        _, changed = await _run("git", "diff", "--name-only", before, "HEAD",
                                cwd=str(REPO_DIR))
        if any(f in changed.split() for f in ("pyproject.toml", "requirements.txt")):
            emit("deps", "INSTALLING DEPENDENCIES…")
            code, out = await _run(sys.executable, "-m", "pip", "install",
                                   "-e", f"{REPO_DIR}[pi]", timeout=600)
            if code != 0:
                # [pi] extras (e.g. gpiod) can fail on Pi OS; fall back to base.
                code, out = await _run(sys.executable, "-m", "pip", "install",
                                       "-e", str(REPO_DIR), timeout=600)
            if code != 0:
                tail = out.splitlines()[-1] if out else "error"
                emit("error", f"DEP INSTALL FAILED: {tail}")
                return False
        return True

    async def set_theme(m: dict) -> None:
        """Persist the chosen colour scheme and broadcast it to all clients."""
        try:
            theme = _sanitize_theme(m.get("theme"))
        except (TypeError, ValueError, KeyError):
            return
        await _save_setting("theme", theme)
        bus.emit("theme_update", theme)

    async def set_rotation(m: dict) -> None:
        """Persist the screen rotation (0/90/180/270) and broadcast it. The page
        rotates its own UI in CSS — see web/style.css — so no system display
        reconfiguration is needed and touch stays aligned with the picture."""
        try:
            deg = int(m.get("deg")) % 360
        except (TypeError, ValueError):
            return
        if deg not in (0, 90, 180, 270):
            return
        await _save_setting("rotation", deg)
        bus.emit("rotation_update", {"deg": deg})

    async def do_update(_m: dict) -> None:
        """Pull the latest code and restart the service.

        On the sealed car the root filesystem is read-only, so we briefly
        remount it read-write, pull, then re-seal it — leaving it exactly as
        we found it. Restarts via systemd with --no-block so the request
        survives this process being killed; the page reloads itself once it
        reconnects to the freshly started server (see app.js).
        """
        def emit(stage: str, message: str) -> None:
            bus.emit("update_status", {"stage": stage, "message": message})

        was_readonly = await _root_is_readonly()
        if was_readonly:
            emit("unlocking", "UNLOCKING FILESYSTEM…")
            code, _ = await _run("sudo", "-n", FS_HELPER, "rw")
            if code != 0:
                emit("error", "COULD NOT UNLOCK FILESYSTEM")
                return

        try:
            updated = await _pull_and_install(emit)
        finally:
            if was_readonly:
                await _run("sync")
                await _run("sudo", "-n", FS_HELPER, "ro")

        if updated:
            log.info("update pulled new code, restarting service")
            emit("applying", "UPDATED — RESTARTING…")
            code, _ = await _run("systemctl", "--user", "restart", "--no-block",
                                 "fieldrig-server.service", timeout=15)
            if code != 0:
                emit("manual", "UPDATED — RESTART REQUIRED")

    # --- Bluetooth pairing needs a writable /var/lib/bluetooth ------------
    # BlueZ persists pairing keys (and the auto-trust flag) under
    # /var/lib/bluetooth, which lives on the sealed read-only root. Without a
    # write window a freshly paired phone is forgotten on the next power-cycle.
    # So PAIR MODE briefly remounts read-write, lets the key + auto-trust land
    # on disk during the discoverable window, then re-seals -- the same trick
    # the UPDATE button uses. Reconnecting on later drives only *reads* the
    # key, which is fine on a read-only root.
    pairing = {"we_unsealed": False, "reseal": None}

    async def _reseal_after_pairing(delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise
        await _run("sync")
        await _run("sudo", "-n", FS_HELPER, "ro")
        pairing["we_unsealed"] = False
        log.info("re-sealed root after bluetooth pairing window")

    async def bt_pairing_mode() -> None:
        # Cancel any pending re-seal; we're (re)opening the window.
        task = pairing["reseal"]
        if task is not None and not task.done():
            task.cancel()
        if await _root_is_readonly():
            await _run("sudo", "-n", FS_HELPER, "rw")
            pairing["we_unsealed"] = True
        await audio.bt_pairing_mode()
        # Re-seal a bit after the discoverable window closes, covering the
        # pairing key plus the auto-trust write that follows a successful pair.
        # Only if *we* unsealed -- never re-seal a deliberately writable box.
        if pairing["we_unsealed"]:
            pairing["reseal"] = asyncio.create_task(
                _reseal_after_pairing(BT_DISCOVERABLE_SECONDS + 10))

    def _flush_on_paired(event: str, data: Any) -> None:
        # Flush the key to disk the instant a phone pairs, so even an immediate
        # power-off keeps it; the window stays open for the auto-trust write.
        asyncio.ensure_future(_run("sync"))

    bus.subscribe("bluetooth_paired", _flush_on_paired)

    async def bt_remove(mac: str) -> None:
        # Forgetting a device deletes it from /var/lib/bluetooth -- a write to
        # the sealed root -- so do it inside a brief read-write window, then
        # re-seal. Unlike pairing this is a one-shot, so we seal right back.
        # If a pairing window is already open we won't have unsealed here, so
        # we leave that window (and its scheduled re-seal) untouched.
        was_ro = await _root_is_readonly()
        if was_ro:
            await _run("sudo", "-n", FS_HELPER, "rw")
        try:
            await audio.bt_remove(mac)
        finally:
            if was_ro:
                await _run("sync")
                await _run("sudo", "-n", FS_HELPER, "ro")

    # Commands the page may send over /ws. Each returns a coroutine.
    commands = {
        "play_pause": lambda m: audio.play_pause(),
        "next": lambda m: audio.next_track(),
        "previous": lambda m: audio.previous_track(),
        "volume_up": lambda m: audio.volume_up(),
        "volume_down": lambda m: audio.volume_down(),
        "toggle_mute": lambda m: audio.toggle_mute(),
        "bt_pairing_mode": lambda m: bt_pairing_mode(),
        "bt_refresh": lambda m: audio.bt_refresh(),
        "bt_connect": lambda m: audio.bt_connect(m["mac"]),
        "bt_disconnect": lambda m: audio.bt_disconnect(m["mac"]),
        "bt_remove": lambda m: bt_remove(m["mac"]),
        "obd_refresh_dtc": lambda m: obd.refresh_dtcs(),
        "obd_clear_dtc": lambda m: obd.clear_dtcs(),
        "app_update": do_update,
        "set_theme": set_theme,
        "set_rotation": set_rotation,
    }

    @app.get("/api/state")
    async def state() -> dict:
        return {
            "version": __version__,
            "theme": _load_theme(),
            "rotation": _load_rotation(),
            "audio": await audio.ui_data(),
            "obd": await obd.ui_data(),
            "camera": await camera.ui_data(),
            "statuses": await manager.statuses(),
        }

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        hub.clients.add(ws)
        log.info("UI client connected (%d total)", len(hub.clients))
        try:
            while True:
                try:
                    msg = json.loads(await ws.receive_text())
                except json.JSONDecodeError:
                    continue
                handler = commands.get(msg.get("cmd"))
                if handler is None:
                    log.warning("unknown command %r", msg.get("cmd"))
                    continue
                # Fire and forget: results surface as bus events.
                asyncio.create_task(handler(msg))
        except WebSocketDisconnect:
            pass
        finally:
            hub.clients.discard(ws)

    @app.get("/camera.mjpg")
    async def camera_feed():
        # Live UVC capture -> multipart/x-mixed-replace stream consumed by an
        # <img> on the camera screen. 503 until the card is detected, so the
        # page can show its OFFLINE card instead of a broken image.
        if not camera.camera.connected:
            return JSONResponse({"error": "no camera connected"}, status_code=503)
        return StreamingResponse(
            camera.mjpeg_stream(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    return app
