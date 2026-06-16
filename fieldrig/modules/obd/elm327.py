"""ELM327 access via python-OBD.

Blocking on purpose -- serial I/O to the dongle is slow (tens of ms per
query). The module calls every method here through asyncio.to_thread so the
event loop never stalls. python-OBD is an optional [pi] dependency; without
it (dev boxes) the wrapper reports unavailable and the OBD screen stays
offline, exactly like the other modules.

The Pi is a read-only *reader* of the car: we pull live PIDs and trouble
codes. CLEAR_DTC is the one write, and it touches the ECU, not the sealed
filesystem -- so it's safe even when the card is mounted read-only.
"""

from __future__ import annotations

from typing import Any

from ...config import OBD_BAUDRATE, OBD_PORT, OBD_TIMEOUT
from ...logging_setup import get_module_logger

log = get_module_logger("obd")

# key -> (python-OBD command name, converter from the raw magnitude).
# python-OBD returns SI-ish units; the dashboard wants imperial.
_LIVE_PIDS = {
    "speed_mph":   ("SPEED",        lambda v: v * 0.621371),   # km/h -> mph
    "rpm":         ("RPM",          lambda v: v),              # rev/min
    "fuel_pct":    ("FUEL_LEVEL",   lambda v: v),              # percent
    "coolant_f":   ("COOLANT_TEMP", lambda v: v * 9 / 5 + 32),  # degC -> degF
    "voltage":     ("CONTROL_MODULE_VOLTAGE", lambda v: v),     # volts
}


class Elm327:
    def __init__(self) -> None:
        try:
            import obd
            self._obd = obd
            self.available = True
            # python-OBD is chatty at INFO; keep it to real problems.
            import logging
            logging.getLogger("obd").setLevel(logging.WARNING)
        except ImportError:
            self._obd = None
            self.available = False
            log.info("python-OBD not installed; OBD-II control disabled")
        self._conn: Any = None

    @property
    def connected(self) -> bool:
        return self._conn is not None and self._conn.is_connected()

    # --- lifecycle (all blocking; call via asyncio.to_thread) -------------

    def connect(self) -> bool:
        """Open the adapter, autoscanning serial ports unless OBD_PORT is set.
        Returns True only when a live ECU link is established."""
        if not self.available or self.connected:
            return self.connected
        try:
            conn = self._obd.OBD(
                portstr=OBD_PORT, baudrate=OBD_BAUDRATE,
                timeout=OBD_TIMEOUT, fast=False,
            )
            if conn.is_connected():
                self._conn = conn
                log.info("ELM327 connected on %s", conn.port_name())
                return True
            conn.close()
        except Exception:
            log.exception("ELM327 connect failed")
        return False

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    # --- reads (blocking) -------------------------------------------------

    def read_live(self) -> dict[str, float] | None:
        """One sweep of the live PIDs. None means the link dropped."""
        if not self.connected:
            return None
        out: dict[str, float] = {}
        any_ok = False
        for key, (cmd_name, conv) in _LIVE_PIDS.items():
            cmd = getattr(self._obd.commands, cmd_name, None)
            if cmd is None:
                continue
            try:
                resp = self._conn.query(cmd)
            except Exception:
                continue
            if resp is None or resp.is_null():
                continue
            any_ok = True
            try:
                out[key] = round(float(resp.value.magnitude), 1)
            except (AttributeError, TypeError, ValueError):
                pass
        # A connected adapter that answers nothing usually means the ignition
        # went off (ECU asleep) -- treat as a dropped link so we reconnect.
        if not any_ok and not self.connected:
            return None
        return out

    def read_dtcs(self) -> list[dict[str, str]]:
        """Stored diagnostic trouble codes as [{code, desc}, ...]."""
        if not self.connected:
            return []
        try:
            resp = self._conn.query(self._obd.commands.GET_DTC, force=True)
        except Exception:
            log.exception("GET_DTC failed")
            return []
        if resp is None or resp.is_null() or not resp.value:
            return []
        codes = []
        for entry in resp.value:
            code = entry[0] if len(entry) else ""
            desc = entry[1] if len(entry) > 1 else ""
            codes.append({"code": code, "desc": desc or "Unknown code"})
        return codes

    def clear_dtcs(self) -> bool:
        """Clear stored codes + the check-engine light. Writes to the ECU."""
        if not self.connected:
            return False
        try:
            self._conn.query(self._obd.commands.CLEAR_DTC, force=True)
            return True
        except Exception:
            log.exception("CLEAR_DTC failed")
            return False
