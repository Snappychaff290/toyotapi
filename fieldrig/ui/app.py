"""FieldRig Textual application.

Owns the core engine (event bus, module manager, hardware watcher,
power monitor) and the screen stack. Nav buttons from any screen
bubble up here.
"""

import asyncio

from textual.app import App
from textual.binding import Binding
from textual.widgets import Button

from ..core import EventBus, ModuleManager
from ..core.hardware import HardwareWatcher
from ..core.power import PowerMonitor
from ..logging_setup import get_module_logger, setup_logging
from ..modules.audio import AudioModule
from ..modules.camera import CameraModule
from ..modules.obd import ObdModule
from .screens import AudioScreen, BluetoothScreen, HomeScreen, PlaceholderScreen

log = get_module_logger("boot")


class FieldRigApp(App):
    TITLE = "FIELDRIG VEHICLE"
    CSS_PATH = "fieldrig.tcss"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "go_home", "Home"),
    ]
    SCREENS = {
        "home": HomeScreen,
        "audio": AudioScreen,
        "bluetooth": BluetoothScreen,
        "nav": lambda: PlaceholderScreen(
            "NAVIGATION", "◈", 5, "GPSD · OFFLINE MBTILES MAPS · HEADING", "nav"),
        "obd": lambda: PlaceholderScreen(
            "VEHICLE TELEMETRY", "▣", 4, "OBD-II · FUEL RANGE · WARNINGS", "obd"),
        "radio": lambda: PlaceholderScreen(
            "RADIO", "≋", 6, "RTL-SDR · SPECTRUM · SCANNER PRESETS", "radio"),
        "mesh": lambda: PlaceholderScreen(
            "MESH NETWORK", "✉", 7, "MESHTASTIC · NODES · MESSAGING", "mesh"),
        "camera": lambda: PlaceholderScreen(
            "CAMERA", "◉", 8, "UVC CAPTURE · OPENCV FEED", "camera"),
        "system": lambda: PlaceholderScreen(
            "SYSTEM", "⚙", 9, "CPU · RAM · MODULE HEALTH · SETTINGS", "system"),
    }

    def __init__(self) -> None:
        super().__init__()
        setup_logging()
        self.bus = EventBus()
        self.manager = ModuleManager(self.bus)
        self.audio = AudioModule(self.bus)
        self.manager.register(self.audio)
        # OBD + camera run headless in the TUI (a debug console); their screens
        # stay placeholders here -- the live UI for them is the web kiosk.
        self.manager.register(ObdModule(self.bus))
        self.manager.register(CameraModule(self.bus))
        self.hardware = HardwareWatcher(self.bus)
        self.power = PowerMonitor(self.bus)
        # Cache of the last audio_update so screens mounting later can
        # render current state immediately instead of waiting for the
        # next event.
        self.audio_state: dict = {}
        self.bus.subscribe("audio_update", self._cache_audio_state)

    def _cache_audio_state(self, event: str, data) -> None:
        self.audio_state = data or {}

    async def on_mount(self) -> None:
        self.bus.attach_loop(asyncio.get_running_loop())
        self.push_screen("home")
        self.run_worker(self._start_core(), exclusive=False)

    async def _start_core(self) -> None:
        log.info("FieldRig starting")
        await self.manager.start_all()
        self.hardware.start()
        await self.power.start()
        log.info("core engine up")

    # --- navigation -------------------------------------------------------

    def goto(self, name: str) -> None:
        """Collapse to home, then open the destination tab."""
        while len(self.screen_stack) > 2:
            self.pop_screen()
        if name != "home":
            self.push_screen(name)

    def action_go_home(self) -> None:
        self.goto("home")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "nav-back":
            if len(self.screen_stack) > 2:
                self.pop_screen()
        elif button_id.startswith("nav-"):
            self.goto(button_id.removeprefix("nav-"))

    # --- shutdown -----------------------------------------------------------

    async def action_quit(self) -> None:
        log.info("FieldRig shutting down")
        await self.power.stop()
        self.hardware.stop()
        await self.manager.stop_all()
        self.exit()
