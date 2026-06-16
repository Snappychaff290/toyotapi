#!/usr/bin/env bash
# FieldRig Phase 1 / step 4: Python venv + FieldRig install with Pi extras.
#
# gpiod>=2.1 requires libgpiod C library v2; Raspberry Pi OS Bookworm ships
# v1.6. If pip fails building gpiod, the script falls back to installing
# pyaudio and pyudev only — GPIO ignition sense degrades gracefully.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$HOME/.local/share/fieldrig/venv"

echo "==> Creating venv at ${VENV}"
mkdir -p "$(dirname "$VENV")"
python3 -m venv "$VENV"

echo "==> Installing FieldRig (+ Pi hardware extras)"
"$VENV/bin/pip" install --upgrade pip

if ! "$VENV/bin/pip" install -e "${REPO_DIR}[pi]"; then
    echo "    Full [pi] install failed (likely gpiod/libgpiod version mismatch)"
    echo "    Installing without gpiod — GPIO ignition sense will be unavailable"
    "$VENV/bin/pip" install -e "${REPO_DIR}"
    "$VENV/bin/pip" install pyaudio pyudev
fi

echo "==> Smoke check"
"$VENV/bin/python" -m fieldrig --check || true

echo "==> Done. Next: ./05-autostart.sh"
