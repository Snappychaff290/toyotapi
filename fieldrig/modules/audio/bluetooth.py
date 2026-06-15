"""BlueZ control via bluetoothctl.

The Pi plays the head-unit role: phones pair *to* it and stream audio
in over A2DP (PipeWire/WirePlumber does the actual sink + routing).
PairingAgent keeps a persistent bluetoothctl session registered as a
NoInputNoOutput agent so incoming pairing just works, and the Bluetooth
class covers device management (list/connect/disconnect/trust/remove).
"""

import asyncio
import re
import shutil
from dataclasses import dataclass, field

from ...config import BT_ALIAS, BT_DISCOVERABLE_SECONDS, BT_SCAN_SECONDS
from ...core.events import EventBus
from ...logging_setup import get_module_logger

log = get_module_logger("audio")

_DEVICE_LINE = re.compile(r"^Device ((?:[0-9A-F]{2}:){5}[0-9A-F]{2}) (.+)$", re.I)


@dataclass
class BTDevice:
    mac: str
    name: str
    paired: bool = False
    connected: bool = False
    trusted: bool = False
    icon: str = field(default="", repr=False)

    @property
    def flags(self) -> str:
        parts = []
        if self.connected:
            parts.append("CONNECTED")
        elif self.paired:
            parts.append("PAIRED")
        if self.trusted:
            parts.append("TRUSTED")
        return ",".join(parts) or "NEW"


class PairingAgent:
    """Persistent bluetoothctl session acting as the pairing agent.

    NoInputNoOutput capability means a phone tapping "FieldRig" pairs
    without any confirmation on the Pi -- head-unit behavior. The
    session also answers the service-authorization prompts some phones
    raise, and emits bluetooth_paired so the UI refreshes immediately.

    The adapter stays pairable but hidden; PAIR MODE on the Bluetooth
    screen flips discoverable on, and BlueZ's discoverable-timeout
    hides it again automatically.
    """

    def __init__(self, bus: EventBus, alias: str = BT_ALIAS) -> None:
        self.bus = bus
        self.alias = alias
        self.active = False
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task | None = None

    async def start(self) -> bool:
        if shutil.which("bluetoothctl") is None:
            log.info("bluetoothctl not found; pairing agent disabled")
            return False
        try:
            self._proc = await asyncio.create_subprocess_exec(
                "bluetoothctl",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError:
            log.exception("could not start bluetoothctl agent session")
            return False
        self._reader = asyncio.create_task(self._read_loop())
        for command in (
            "power on",
            f"system-alias {self.alias}",
            "agent NoInputNoOutput",
            "default-agent",
            "pairable on",
            f"discoverable-timeout {BT_DISCOVERABLE_SECONDS}",
        ):
            await self._send(command)
        self.active = True
        log.info("pairing agent up; Pi pairs as %r when discoverable", self.alias)
        return True

    async def _send(self, command: str) -> None:
        if self._proc is None or self._proc.stdin is None:
            return
        try:
            self._proc.stdin.write((command + "\n").encode())
            await self._proc.stdin.drain()
        except (ConnectionResetError, BrokenPipeError):
            log.warning("agent session died sending %r", command)
            self.active = False

    async def _read_loop(self) -> None:
        # Chunked reads, not readline: bluetoothctl's interactive
        # prompts ("...? (yes/no):") don't end with a newline.
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            chunk = await self._proc.stdout.read(512)
            if not chunk:
                break
            text = chunk.decode(errors="replace")
            if "(yes/no)" in text or "Authorize service" in text:
                log.info("agent auto-accepting: %s", text.strip())
                await self._send("yes")
            if "Paired: yes" in text:
                log.info("device paired to Pi")
                self.bus.emit("bluetooth_paired", None)
        self.active = False

    async def set_discoverable(self, on: bool = True) -> None:
        await self._send(f"discoverable {'on' if on else 'off'}")

    async def stop(self) -> None:
        self.active = False
        if self._reader is not None:
            self._reader.cancel()
            self._reader = None
        if self._proc is not None:
            try:
                self._proc.stdin.write(b"exit\n")
                await self._proc.stdin.drain()
                await asyncio.wait_for(self._proc.wait(), 3)
            except (asyncio.TimeoutError, OSError, ConnectionResetError):
                self._proc.kill()
            self._proc = None


class Bluetooth:
    def __init__(self) -> None:
        self.available = shutil.which("bluetoothctl") is not None
        if not self.available:
            log.info("bluetoothctl not found; Bluetooth management disabled")

    async def _ctl(self, *args: str, timeout: float = 10.0) -> str | None:
        if not self.available:
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
                "bluetoothctl", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout)
            return stdout.decode(errors="replace")
        except (asyncio.TimeoutError, OSError):
            log.exception("bluetoothctl %s failed", " ".join(args))
            return None

    async def set_power(self, on: bool) -> bool:
        out = await self._ctl("power", "on" if on else "off")
        return bool(out and "succeeded" in out)

    async def powered(self) -> bool:
        out = await self._ctl("show")
        return bool(out and re.search(r"Powered:\s*yes", out))

    async def scan(self, seconds: int = BT_SCAN_SECONDS) -> None:
        """Blocking discovery burst; results land in `devices()` afterwards."""
        await self._ctl("--timeout", str(seconds), "scan", "on",
                        timeout=seconds + 5)

    async def devices(self) -> list[BTDevice]:
        out = await self._ctl("devices")
        if not out:
            return []
        found: list[BTDevice] = []
        for line in out.splitlines():
            match = _DEVICE_LINE.match(line.strip())
            if not match:
                continue
            device = BTDevice(mac=match.group(1).upper(), name=match.group(2))
            info = await self._ctl("info", device.mac)
            if info:
                device.paired = bool(re.search(r"Paired:\s*yes", info))
                device.connected = bool(re.search(r"Connected:\s*yes", info))
                device.trusted = bool(re.search(r"Trusted:\s*yes", info))
            found.append(device)
        # Connected first, then paired, then the rest.
        found.sort(key=lambda d: (not d.connected, not d.paired, d.name.lower()))
        return found

    async def connected_device(self) -> BTDevice | None:
        for device in await self.devices():
            if device.connected:
                return device
        return None

    async def _verb(self, verb: str, mac: str, timeout: float = 20.0) -> tuple[bool, str]:
        out = await self._ctl(verb, mac, timeout=timeout)
        if out is None:
            return False, f"{verb} failed (no bluetoothctl)"
        ok = "successful" in out or "succeeded" in out or "removed" in out.lower()
        # Last non-empty line is the most useful message bluetoothctl prints.
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        return ok, (lines[-1] if lines else verb)

    async def pair(self, mac: str) -> tuple[bool, str]:
        return await self._verb("pair", mac, timeout=30.0)

    async def connect(self, mac: str) -> tuple[bool, str]:
        return await self._verb("connect", mac)

    async def disconnect(self, mac: str) -> tuple[bool, str]:
        return await self._verb("disconnect", mac)

    async def trust(self, mac: str) -> tuple[bool, str]:
        return await self._verb("trust", mac)

    async def remove(self, mac: str) -> tuple[bool, str]:
        return await self._verb("remove", mac)
