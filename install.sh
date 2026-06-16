#!/usr/bin/env bash
# FieldRig one-shot installer for a fresh Raspberry Pi OS Lite 64-bit on a Pi 5.
#
#   git clone <repo> ~/fieldrig
#   cd ~/fieldrig
#   ./install.sh
#
# Runs every setup step in order: system packages + services, fonts, tty1
# console autologin, the Python venv + app install, and the cage/Chromium
# kiosk autostart. Re-runnable: each step is idempotent.
#
# Pass --reboot to reboot automatically when finished.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SETUP="$REPO_DIR/setup"
AUTO_REBOOT=0
[ "${1:-}" = "--reboot" ] && AUTO_REBOOT=1

# --- sanity checks -----------------------------------------------------------

if [ "$(id -u)" -eq 0 ]; then
    echo "Run this as your normal user, NOT root/sudo." >&2
    echo "It installs per-user systemd services and uses your \$HOME." >&2
    exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
    echo "apt-get not found — this installer targets Raspberry Pi OS (Debian)." >&2
    exit 1
fi

echo "================================================================"
echo " FieldRig install"
echo "   repo:  $REPO_DIR"
echo "   user:  $USER"
echo "================================================================"

# --- run the numbered steps in order ----------------------------------------

run_step() {
    local script="$1"
    echo
    echo "########## $script ##########"
    bash "$SETUP/$script"
}

run_step 01-system.sh
run_step 02-display.sh
run_step 03-autologin.sh
run_step 04-python-env.sh
run_step 05-autostart.sh

# --- done --------------------------------------------------------------------

echo
echo "================================================================"
echo " FieldRig install complete."
echo
echo " A reboot applies the new group memberships and starts the kiosk:"
echo " ignition on -> autologin -> server -> Chromium fullscreen."
echo "================================================================"

if [ "$AUTO_REBOOT" -eq 1 ]; then
    echo "Rebooting now..."
    sudo reboot
else
    echo "Reboot when ready:  sudo reboot"
fi
