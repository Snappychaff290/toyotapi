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
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

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
    }

    @app.get("/api/state")
    async def state() -> dict:
        return {
            "version": __version__,
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
