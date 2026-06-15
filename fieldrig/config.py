"""Central configuration for FieldRig."""

import os
from pathlib import Path

APP_NAME = "FieldRig"
VERSION = "0.3.0"

# --- UI ---
WAVEFORM_BARS = 24
WAVEFORM_FPS = 10
PROGRESS_WIDTH = 28

# --- Audio ---
MPRIS_POLL_SECONDS = 1.0
BT_POLL_EVERY_N_TICKS = 5       # bluetooth state poll = every Nth audio poll
BT_SCAN_SECONDS = 8
# The Pi is the A2DP *sink*: phones pair to it and stream audio in,
# which PipeWire routes out the aux jack to the amp.
BT_ALIAS = "FieldRig"           # name phones see when pairing
BT_DISCOVERABLE_SECONDS = 120   # pairing-mode window before auto-hiding
VOLUME_STEP = 0.05
MAX_VOLUME = 1.0

# --- Power monitor ---
# BCM pin wired to the ignition-switched 12V sense divider.
IGNITION_GPIO_PIN = int(os.environ.get("FIELDRIG_IGNITION_PIN", "17"))
POWER_LOSS_DEBOUNCE_SECONDS = 3.0
SHUTDOWN_GRACE_SECONDS = 10
# Real shutdown is opt-in so a flaky sense wire can't kill a dev session.
ENABLE_SHUTDOWN = os.environ.get("FIELDRIG_ENABLE_SHUTDOWN", "0") == "1"


def log_dir() -> Path:
    """/var/log/fieldrig on the Pi, ~/.local/state fallback for dev."""
    system = Path("/var/log/fieldrig")
    try:
        system.mkdir(parents=True, exist_ok=True)
        probe = system / ".write-test"
        probe.touch()
        probe.unlink()
        return system
    except OSError:
        local = Path.home() / ".local" / "state" / "fieldrig" / "logs"
        local.mkdir(parents=True, exist_ok=True)
        return local
