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
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..core import EventBus, ModuleManager
from ..core.hardware import HardwareWatcher
from ..core.power import PowerMonitor
from ..core.sysinfo import sysinfo_task
from ..logging_setup import get_module_logger, setup_logging
from ..modules.audio import AudioModule

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
DEFAULT_THEME = {"h": 135, "s": "100%"}


def _load_theme() -> dict:
    try:
        t = json.loads(SETTINGS_FILE.read_text()).get("theme") or {}
        return {"h": int(t["h"]), "s": str(t["s"])}
    except Exception:
        return dict(DEFAULT_THEME)


def _sanitize_theme(h: Any, s: Any) -> dict:
    """Clamp to a safe hue/saturation; these get interpolated into CSS."""
    hue = max(0, min(360, int(h)))
    sat = max(0, min(100, int(str(s).rstrip("%"))))
    return {"h": hue, "s": f"{sat}%"}


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
    manager.register(audio)
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
        """Persist the chosen phosphor colour and broadcast it to all clients.
        Briefly remounts read-write if the root is sealed (same as updates)."""
        try:
            theme = _sanitize_theme(m.get("h"), m.get("s"))
        except (TypeError, ValueError):
            return

        was_readonly = await _root_is_readonly()
        if was_readonly:
            await _run("sudo", "-n", FS_HELPER, "rw")
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            try:
                data = json.loads(SETTINGS_FILE.read_text())
            except Exception:
                data = {}
            data["theme"] = theme
            SETTINGS_FILE.write_text(json.dumps(data))
        except OSError:
            log.warning("could not persist theme to %s", SETTINGS_FILE)
        finally:
            if was_readonly:
                await _run("sync")
                await _run("sudo", "-n", FS_HELPER, "ro")

        bus.emit("theme_update", theme)

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

    # Commands the page may send over /ws. Each returns a coroutine.
    commands = {
        "play_pause": lambda m: audio.play_pause(),
        "next": lambda m: audio.next_track(),
        "previous": lambda m: audio.previous_track(),
        "volume_up": lambda m: audio.volume_up(),
        "volume_down": lambda m: audio.volume_down(),
        "toggle_mute": lambda m: audio.toggle_mute(),
        "bt_pairing_mode": lambda m: audio.bt_pairing_mode(),
        "bt_refresh": lambda m: audio.bt_refresh(),
        "bt_connect": lambda m: audio.bt_connect(m["mac"]),
        "bt_disconnect": lambda m: audio.bt_disconnect(m["mac"]),
        "bt_remove": lambda m: audio.bt_remove(m["mac"]),
        "app_update": do_update,
        "set_theme": set_theme,
    }

    @app.get("/api/state")
    async def state() -> dict:
        return {
            "version": __version__,
            "theme": _load_theme(),
            "audio": await audio.ui_data(),
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
    async def camera() -> JSONResponse:
        # Phase 8: OpenCV capture -> multipart/x-mixed-replace stream.
        return JSONResponse({"error": "camera module arrives in Phase 8"},
                            status_code=503)

    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    return app
