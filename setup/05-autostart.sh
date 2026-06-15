#!/usr/bin/env bash
# FieldRig Phase 1 / step 5: boot into the app automatically.
# Installs a launcher and a KDE autostart entry that opens a fullscreen
# konsole running FieldRig as soon as Plasma is up.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Installing server user service"
mkdir -p "$HOME/.config/systemd/user"
cp files/fieldrig-server.service "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable fieldrig-server.service

echo "==> Installing kiosk launcher to ~/.local/bin/fieldrig-launch"
install -Dm755 files/fieldrig-launch.sh "$HOME/.local/bin/fieldrig-launch"

echo "==> Installing autostart entry (Chromium kiosk)"
mkdir -p "$HOME/.config/autostart"
sed "s|@HOME@|$HOME|g" files/fieldrig.desktop \
    > "$HOME/.config/autostart/fieldrig.desktop"

echo "==> Done. Reboot to test: ignition on -> FieldRig fullscreen."
