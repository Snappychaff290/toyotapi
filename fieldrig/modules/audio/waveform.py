"""Waveform analyzer feeding the dashboard's bar display.

Real mode: PyAudio captures from the default input (USB audio adapter
tapped off the aux line, Phase 2 hardware) on a worker thread, slices
each chunk into N time-domain bars, and emits "waveform_update".

Fallback mode: no input device -> a playback-driven simulation so the
UI looks alive everywhere, including dev machines.
"""

import asyncio
import math
import random
import threading
from array import array

from ...config import WAVEFORM_BARS, WAVEFORM_FPS
from ...logging_setup import get_module_logger
from ...core.events import EventBus

log = get_module_logger("audio")

RATE = 44100
CHUNK = 2048
SMOOTHING = 0.5  # fraction of previous level kept each frame


class WaveformAnalyzer:
    def __init__(self, bus: EventBus, bars: int = WAVEFORM_BARS) -> None:
        self.bus = bus
        self.bars = bars
        self.mode = "off"  # off | capture | simulated
        self.playing = False
        self._levels = [0.0] * bars
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._try_capture():
            self.mode = "capture"
        else:
            self.mode = "simulated"
            self._task = asyncio.ensure_future(self._simulate())
        log.info("waveform analyzer started in %s mode", self.mode)

    def set_playing(self, playing: bool) -> None:
        """Drives the simulation; harmless in capture mode."""
        self.playing = playing

    # --- real capture -------------------------------------------------

    def _try_capture(self) -> bool:
        try:
            import pyaudio
        except ImportError:
            return False
        try:
            pa = pyaudio.PyAudio()
            pa.get_default_input_device_info()
        except Exception:
            try:
                pa.terminate()
            except Exception:
                pass
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._capture_loop, args=(pa,), daemon=True,
            name="fieldrig-waveform",
        )
        self._thread.start()
        return True

    def _capture_loop(self, pa) -> None:
        import pyaudio

        stream = None
        try:
            stream = pa.open(format=pyaudio.paInt16, channels=1, rate=RATE,
                             input=True, frames_per_buffer=CHUNK)
            slice_size = max(1, CHUNK // self.bars)
            while not self._stop.is_set():
                data = stream.read(CHUNK, exception_on_overflow=False)
                samples = array("h", data)
                for i in range(self.bars):
                    chunk = samples[i * slice_size:(i + 1) * slice_size]
                    level = (sum(abs(s) for s in chunk) / len(chunk) / 32768.0
                             if chunk else 0.0)
                    self._levels[i] = (SMOOTHING * self._levels[i]
                                       + (1 - SMOOTHING) * min(1.0, level * 3.0))
                self.bus.emit_threadsafe("waveform_update", list(self._levels))
        except Exception:
            log.exception("waveform capture failed")
        finally:
            if stream is not None:
                stream.close()
            pa.terminate()

    # --- simulation ---------------------------------------------------

    async def _simulate(self) -> None:
        t = 0.0
        while True:
            await asyncio.sleep(1.0 / WAVEFORM_FPS)
            t += 1.0 / WAVEFORM_FPS
            for i in range(self.bars):
                if self.playing:
                    wave = abs(math.sin(t * 2.4 + i * 0.55))
                    target = 0.15 + 0.75 * wave * (0.55 + random.random() * 0.45)
                else:
                    # Gentle idle ripple so the display never looks dead.
                    target = 0.04 + 0.06 * abs(math.sin(t * 0.8 + i * 0.4))
                self._levels[i] = (SMOOTHING * self._levels[i]
                                   + (1 - SMOOTHING) * target)
            self.bus.emit("waveform_update", list(self._levels))

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self.mode = "off"
