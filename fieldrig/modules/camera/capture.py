"""UVC capture via OpenCV.

A background thread owns the cv2.VideoCapture (its read() blocks) and keeps
the latest JPEG-encoded frame in memory. The server's MJPEG endpoint pulls
that frame asynchronously, so capture and HTTP never block each other and the
event loop stays clear. OpenCV is an optional [pi] dependency; without it the
camera reports unavailable, like every other module on a dev box.
"""

from __future__ import annotations

import threading
import time

from ...config import (
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_JPEG_QUALITY,
    CAMERA_WIDTH,
)
from ...logging_setup import get_module_logger

log = get_module_logger("camera")

# Consecutive failed reads before we treat the card as unplugged.
_MAX_READ_FAILURES = 30
# How long open() waits for the first frame before calling it a dud.
_OPEN_TIMEOUT = 2.5


class Camera:
    def __init__(self) -> None:
        try:
            import cv2
            self._cv2 = cv2
            self.available = True
        except ImportError:
            self._cv2 = None
            self.available = False
            log.info("OpenCV not installed; camera disabled")
        self.connected = False
        self.device: int | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._cond = threading.Condition()
        self._frame: bytes | None = None
        self._frame_id = 0

    # --- lifecycle (blocking; call open/close via asyncio.to_thread) ------

    def open(self, index: int) -> bool:
        """Start capturing from /dev/video<index>. Returns True once frames
        are actually flowing (so a device that opens but yields nothing fails
        cleanly and the caller can try the next index)."""
        if not self.available or self.connected:
            return self.connected
        self._stop.clear()
        self._frame = None
        self._thread = threading.Thread(
            target=self._run, args=(index,), daemon=True)
        self._thread.start()
        deadline = time.monotonic() + _OPEN_TIMEOUT
        while time.monotonic() < deadline:
            if not self._thread.is_alive():
                break
            if self.connected:
                return True
            time.sleep(0.05)
        if not self.connected:
            self.close()
        return self.connected

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self.connected = False
        self.device = None

    def latest(self) -> tuple[int, bytes | None]:
        """The most recent JPEG frame and its id (id lets the streamer skip
        re-sending a frame it already sent)."""
        with self._cond:
            return self._frame_id, self._frame

    def wait_frame(self, last_id: int, timeout: float) -> tuple[int, bytes | None]:
        """Block until a frame newer than last_id arrives (or timeout)."""
        with self._cond:
            if self._frame_id == last_id:
                self._cond.wait(timeout)
            return self._frame_id, self._frame

    # --- capture thread ---------------------------------------------------

    def _run(self, index: int) -> None:
        cv2 = self._cv2
        cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap = cv2.VideoCapture(index)
        if not cap.isOpened():
            log.info("camera index %d would not open", index)
            cap.release()
            return
        # Request MJPG from the card (most UVC capture cards stream it natively,
        # which keeps USB bandwidth sane at 720p+).
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), CAMERA_JPEG_QUALITY]

        self.device = index
        self.connected = True
        log.info("camera capturing on /dev/video%d", index)
        failures = 0
        frame_interval = 1.0 / max(1, CAMERA_FPS)
        try:
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    failures += 1
                    if failures >= _MAX_READ_FAILURES:
                        log.info("camera /dev/video%d stopped delivering frames", index)
                        break
                    time.sleep(0.05)
                    continue
                failures = 0
                ok, buf = cv2.imencode(".jpg", frame, encode_params)
                if not ok:
                    continue
                with self._cond:
                    self._frame = buf.tobytes()
                    self._frame_id += 1
                    self._cond.notify_all()
                time.sleep(frame_interval)
        finally:
            cap.release()
            self.connected = False
            with self._cond:
                self._cond.notify_all()
